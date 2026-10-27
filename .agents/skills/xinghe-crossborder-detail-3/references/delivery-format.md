# Delivery Format

## No Regeneration In Default Delivery

Default delivery does not include automatic regeneration or suggested regeneration steps. If QA finds issues, report them as notes only. Regenerate only when the user explicitly asks.

## File Naming

Use clear ordered names:

```text
product-platform-module-01.png
product-platform-module-02.png
...
```

Examples:

```text
dress-amazon-module-01.png
makeup-spray-shopify-module-01.png
storage-box-crossborder-module-01.png
```

## Folder Naming

Prefer:

```text
<product-name>-crossborder-detail-v1
```

If saving to user desktop or project folder, create a dedicated folder and do not mix generated images with source images.

## Size Consistency

- Default output ratio: horizontal `16:9`.
- Default script settings: `--size 16:9 --resolution 2k`, unless the user specifies another size such as vertical `900x1200`.
- Every image in one set must use the same ratio and resolution.
- If a generated image has the wrong ratio, mark it in QA and regenerate only if the user asks.

## Response

Return:

1. Generation method: Xinghe deployment helper, fixed API script, or built-in `image_gen` final fallback.
2. Save directory.
3. Numbered image list with purpose.
4. QA notes / optional review items.
5. Final kept count.

## Required Sections

For completed direct-generation tasks, include:

- Product Image Analysis.
- Information Confidence.
- Buyer Demand Map.
- Demand-to-Selling-Point Match.
- Product Type Strategy.
- Platform Profile.
- Reference Visual Style Lock, when references are provided.
- Campaign Style Lock.
- Style System Lock.
- Design Strength Lock.
- Product Identity & Physics Lock.
- Page Task Table.
- Generated Files.
- QA Notes / Optional Review Items.

## Local Stitching Ban

Do not create a contact sheet. Contact sheets, preview grids, stitched boards, or any locally assembled image output are disallowed and must never be treated as generated detail-page modules.

Final delivery should list and preview the individual generated module images directly.
