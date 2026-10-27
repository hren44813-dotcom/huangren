# Fixed API First / image_gen Final Fallback

Use this before final image generation. The Xinghe deployment helper and fixed API route are the primary generation path; built-in `image_gen` is only the final fallback.

## Priority

1. Use the deployment helper from `XINGHE_IMAGE_GENERATOR`, then `%LOCALAPPDATA%\ApiCodexOneClick\tools\generate-image.ps1`.
2. If the deployment helper is missing, use bundled fixed-interface scripts: `scripts/generate_batch.py` for a full set, or `scripts/generate_image.py` for a single module.
3. If the deployment helper and bundled fixed-interface scripts are unavailable, fail, or cannot save/display the generated file, use built-in `image_gen` as the final fallback.
4. If no API key is configured and `image_gen` is also unavailable, return the complete prompt pack and `.env.example` guidance; do not invent images.

## Configuration

The installer or user environment should provide:

```dotenv
OPENAI_IMAGE_GENERATIONS_URL=https://xinghe.xin/v1/images/generations
OPENAI_IMAGE_EDITS_URL=https://xinghe.xin/v1/images/edits
OPENAI_IMAGE_MODEL=gpt-image-2
OPENAI_IMAGE_API_KEY=your-api-key
```

Supported legacy aliases: `IMG_BASE_URL`, `IMG_MODEL`, `IMG_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_API_BASE`, `BASE_URL`, `IMAGE_MODEL`, `OPENAI_MODEL`, `OPENAI_API_KEY`, `API_KEY`.

Routing rule:

- reference images present -> use edits route / helper `-ReferenceImage` / script `--image`.
- text-only prompt -> use generations route / helper without `-ReferenceImage`.

## Deployment Helper Command

Use the exact user-requested size when provided. Examples:

- Horizontal default: `1536x864` or another 16:9 size supported by the helper.
- Ozon/Wildberries vertical: `900x1200` when the user asks for that size.

Use this for each module when a product/reference image exists:

```powershell
$helper = $env:XINGHE_IMAGE_GENERATOR
if (-not $helper) { $helper = Join-Path $env:LOCALAPPDATA 'ApiCodexOneClick\tools\generate-image.ps1' }
$promptFile = "<absolute prompt file path>"
$referenceImages = @("C:\path\to\product.png")
$referenceImageArg = ($referenceImages -join ';')
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $helper `
  -PromptFile $promptFile `
  -ReferenceImage $referenceImageArg `
  -OutputDir "<absolute output directory>" `
  -Size "<requested size, e.g. 900x1200 or 1536x864>" `
  -FileName "module-01.png"
```

For text-only generation, remove `-ReferenceImage`. When multiple product/reference images exist, keep one `-ReferenceImage` argument only and pass a semicolon-joined string such as `$referenceImageArg`; do not pass a PowerShell array or comma-separated multiple paths directly.

## Staggered Concurrent Helper Calls

When generating multiple modules through the deployment helper, prefer staggered concurrency and automatically fall back to serial generation if background jobs fail:

- Submit module 01 as a background job.
- Wait 3 seconds.
- Submit module 02 without waiting for module 01 to finish or land on disk.
- Continue until every module is submitted.
- After submission, wait for all jobs, collect helper output, and verify saved files.
- If `Start-Job`, `Wait-Job`, or `Receive-Job` fails on the customer's computer, stop and clean up background jobs, then retry missing outputs one by one with the same helper arguments.

Each module must have its own prompt file, output filename, and module-specific prompt. If reference images are used, pass one semicolon-joined `ReferenceImageArg` string to `-ReferenceImage`.

```powershell
$serialFallback = $false
$jobs = @()
try {
  foreach ($task in $imageTasks) {
    $jobs += Start-Job -ScriptBlock {
      param($helper, $promptFile, $referenceImageArg, $outputDir, $size, $fileName)
      if ($referenceImageArg) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $helper -PromptFile $promptFile -ReferenceImage $referenceImageArg -OutputDir $outputDir -Size $size -FileName $fileName
      } else {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $helper -PromptFile $promptFile -OutputDir $outputDir -Size $size -FileName $fileName
      }
    } -ArgumentList $helper, $task.PromptFile, $task.ReferenceImageArg, $task.OutputDir, $task.Size, $task.FileName
    Start-Sleep -Seconds 3
  }
  $jobs | Wait-Job | Out-Null
  $results = $jobs | Receive-Job -ErrorAction Stop
} catch {
  $serialFallback = $true
} finally {
  if ($jobs.Count -gt 0) {
    if ($serialFallback) { $jobs | Stop-Job -ErrorAction SilentlyContinue }
    $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
  }
}
if ($serialFallback) {
  $results = @()
  foreach ($task in $imageTasks) {
    $outPath = Join-Path $task.OutputDir $task.FileName
    if (Test-Path -LiteralPath $outPath) { continue }
    if ($task.ReferenceImageArg) {
      $results += & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $helper -PromptFile $task.PromptFile -ReferenceImage $task.ReferenceImageArg -OutputDir $task.OutputDir -Size $task.Size -FileName $task.FileName
    } else {
      $results += & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $helper -PromptFile $task.PromptFile -OutputDir $task.OutputDir -Size $task.Size -FileName $task.FileName
    }
  }
}
```

For a single module, use the normal synchronous helper call.

## Bundled Script Commands

Use only if the deployment helper is missing.

Batch:

```powershell
python .\scripts\generate_batch.py `
  --env-file .env `
  --prompt-dir prompts\product-detail-v1 `
  --image "C:\path\to\product.png" `
  --size "<requested ratio or pixel size, e.g. 900x1200 or 16:9>" `
  --resolution 2k `
  --output-dir generated-images\product-detail-v1
```

Single module:

```powershell
python .\scripts\generate_image.py `
  --env-file .env `
  --prompt-file prompts\module-01.txt `
  --image "C:\path\to\product.png" `
  --size "<requested ratio or pixel size, e.g. 900x1200 or 16:9>" `
  --resolution 2k `
  --output-dir generated-images\product-detail-v1
```

## Failure Handling

- If one module fails, retry once with a shorter prompt that preserves the locks.
- If API credentials are missing, stop script execution and output the prompt files plus `.env.example` instructions.
- If text renders poorly, use fewer labels and shorter copy.
- Do not create contact sheets, preview grids, stitched boards, or any locally assembled image output. They are disallowed and must never be treated as generated detail-page modules.
