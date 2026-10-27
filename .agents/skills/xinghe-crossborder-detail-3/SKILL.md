---
name: xinghe-crossborder-detail-3
description: Cross-border ecommerce detail page image generation skill. Use when Codex needs to turn product photos, selling points, reference detail pages, competitor visuals, or platform requirements into finished cross-border PDP images, Amazon A+ modules, Shopify product modules, Temu/AliExpress selling images, TikTok Shop modules, or Ozon/Wildberries vertical Russian marketplace images. Supports buyer-demand-led planning, user-specified aspect ratios such as 900x1200, information confidence, page task tables, reference visual style adaptation, platform-specific page rhythm, product-consistency and physical-logic locks, Xinghe fixed API/deployment-helper-first generation, and built-in image_gen final fallback.
---

# 星河跨境电商详情4.0

Generate finished cross-border ecommerce detail page images from product photos. Do not stop at strategy or prompts unless the user explicitly asks for prompts only. The default workflow is:

Product image analysis -> information confidence -> buyer demand map -> demand-to-selling-point match -> platform profile -> purchase decision type -> page strategy -> module plan -> reference visual style adaptation when references are provided -> page task table -> style system lock -> design strength lock -> product identity and physics lock -> final image prompts -> image generation -> delivery with file paths and QA notes.

Core formula: buyer demand ranking -> purchase decision type -> page strategy -> module planning -> product selling-point match -> page task allocation -> scene evidence expression -> platform-fit visual system -> product identity and physical-logic lock -> direct final image generation.

A detail page is not a manual and not a poster set. It is a sequence of sales images that removes purchase hesitation while preserving product truth and platform compliance.

## Global Priority Order

When this skill or its reference files contain rules that appear to conflict, interpret and execute them in this priority order:

1. User's explicit request, including requested quantity, platform, size, language, style direction, brand colors, reference style, and module order.
2. Platform profile and compliance: adapt to Amazon, Shopify, Temu, AliExpress, TikTok Shop, Ozon/Wildberries, or the user's named platform; do not fabricate claims, certifications, test data, sales, reviews, medical effects, unsupported parameters, platform badges, or competitor identity.
3. Product truth and product identity: preserve visible product color, structure, material, packaging, decoration, proportions, SKU, logo/nameplate placement, and physical plausibility.
4. Module Plan count and page strategy: generate one image for each planned module unless the user explicitly specifies another count.
5. Buyer-demand task for the current module: each image must solve its assigned buyer question with one matched selling point and visual proof.
6. Platform-fit design strength: avoid plain product posters, repeated templates, empty backgrounds, copied competitor layouts, and unchanged product scale across the set.
7. Reference visual style and creative variation: adapt style, mood, rhythm, and composition devices without copying exact layouts or locking the source photo composition.
8. Optional QA and review notes: disclose issues without automatic regeneration unless the user explicitly asks for regeneration or replacement.

If two same-level rules conflict, choose the option that is more truthful, more compliant, more platform-appropriate, and more aligned with the current module's buyer-demand task.

Direct-generation boundary: every delivered module image must be generated directly by the deployment helper, fixed API script, or built-in `image_gen`. Never create delivered images through local stitching, local layout assembly, local text overlay, local background replacement, local product/background compositing, or local crop-and-recombine workflows. If a prompt asks for a collage-style visual device, the complete collage-style module must be generated in one image-generation call, not assembled locally.

## Image Interface Order

- Always attempt the Xinghe deployment helper or fixed API route first for final image generation.
- Read `references/fallback-generation.md` before generation to resolve the deployment helper, route, scripts, and API configuration.
- Use the deployment helper first. If the helper is missing, use bundled fixed-interface scripts when configured.
- When generating multiple final images through the deployment helper, use the staggered concurrent helper-call rule in `references/fallback-generation.md`: submit one job, wait 3 seconds, submit the next job without waiting for file output, then wait for all jobs after submission.
- Use built-in `image_gen` only as the final fallback when the deployment helper and bundled fixed-interface scripts are unavailable, fail, or cannot save/display the result.

## Non-Negotiables

- Use horizontal modules by default for cross-border detail pages, Amazon A+, Shopify PDP modules, Temu/AliExpress details, and TikTok Shop product modules.
- If the user specifies a platform size, vertical aspect ratio, Ozon/Wildberries, Russian language, or `900x1200`, that explicit request overrides the horizontal default.
- Keep one consistent aspect ratio and resolution across a set. Default to `16:9 / 2K` unless the user specifies another size.
- If the user specifies image count, platform size, style, brand colors, reference style, or module order, follow the user while preserving compliance.
- Generate final ready-to-use images directly when the user provides product photos and asks for ecommerce detail images.
- Generate each module as a separate image. Do not generate a multi-screen collage as a substitute for separate modules.
- Do not create final images, preview images, or contact sheets through local stitching or local compositing. Saving, renaming, copying, and file checks are allowed; image assembly is not.
- Preserve the product's visible appearance, color, packaging, structure, material look, SKU, logo/nameplate placement, pattern placement, and key details.
- Do not invent brands, certifications, material composition, sales claims, ratings, reviews, test data, medical effects, safety guarantees, waterproof claims, compatibility lists, or professional endorsements.
- Product consistency locks product identity, not the source photo's composition. Preserve product identity and physical logic while changing scene, angle, crop, model presentation, and detail-page layout according to the page role.
- QA is disclosure by default. Do not automatically regenerate unless the user explicitly asks for regeneration, redo, re-create, fix, or replacement.

## Core Workflow

When the user provides product photos and asks for detail pages, A+ modules, PDP images, or cross-border ecommerce images:

1. Start directly. Do not block just because product copy is missing; first analyze visible product information.
2. If the user does not specify image count, default to planning 8 modules, but final image count must follow the `Module Plan`. If the product has enough confirmed information and distinct buyer questions, the plan may expand to 9-12 modules. If the user specifies a count, follow that count exactly and give each image a distinct sales task.
3. Use `wide 16:9 horizontal ecommerce detail module` and `2K` as the default canvas direction unless the user specifies a different size. If the user specifies Ozon/Wildberries, Russian marketplace, Russian copy, vertical PDP, or `900x1200`, activate `Vertical Marketplace Mode`: vertical 3:4 / user-specified pixel size, Russian short copy, product-photography-first layout, restrained information hierarchy.
4. If only product images are provided, create `Product Image Analysis` and `Product Consistency Anchors`.
5. Read `references/buyer-demand-strategy.md` and create `Information Confidence`, `Buyer Demand Map`, `Demand-to-Selling-Point Match`, and `Product Type Strategy`.
6. Read `references/platform-profiles.md`. If the user names a platform, adapt rhythm, density, copy tone, image orientation, and compliance to that platform. If no platform is named, use general cross-border PDP/A+ logic.
7. If reference images or competitor detail pages are provided, read `references/reference-page-analysis.md`. Default to referencing visual style: overall tone, color mood, lighting direction, image density, hierarchy, page rhythm, composition devices, label/card style, and scene atmosphere. Do not copy brand, logo, wording, exact layout, identifiable design, certification marks, ratings, or reviews.
8. Read `references/page-planning-strategy.md` and create `Purchase Decision Type`, `Page Strategy`, `Best Hero Direction`, `Module Plan`, and `Visual Rhythm Plan`. Do not output a material reshoot list.
9. Read `references/page-task-table.md` and create a screen-by-screen `Page Task Table` from the planned modules before prompt writing. The number of final generated images must follow the `Module Plan` count unless the user explicitly specified a different count.
10. Read `references/scene-layout-standard.md`, `references/style-system-standard.md`, `references/design-strength-system.md`, `references/visual-quality-rules.md`, and `references/product-consistency-physics.md`. Create `Scene Layout Plan`, `Style System Lock`, `Visual Quality Lock`, `Design Strength Lock`, and `Product Identity & Physics Lock`.
11. Read `references/anti-template-check.md` and revise the page plan before generation if the set collapses into a repeated template.
12. Read `references/prompt-contract.md` or `references/prompt-templates.md` to assemble standalone prompts. Include the same locks and each module's planning fields in every prompt.
13. Read `references/fallback-generation.md` and generate through the Xinghe deployment helper or fixed API route first, one module per call. For multiple helper calls, submit jobs with the 3-second staggered concurrent rule before waiting for all outputs. Use built-in `image_gen` only as the final fallback when the helper and bundled scripts are unavailable or fail.
14. Deliver generation method, save directory, numbered image list, each image purpose, QA notes, and final kept count.

## Product Image Analysis

Identify:

- Visible category.
- Shape, color, material look, structural parts, accessories, packaging, SKU, and visible text.
- Possible use contexts.
- What is visible fact versus reasonable inference.
- Product consistency anchors: silhouette, proportions, color-area ratio, material appearance, pattern/logo/nameplate placement, structural relationships, and physical contact/scale logic. These anchors preserve product identity only; they do not preserve the source photo background, angle, crop, placement, or white-background single-product composition.

Mark anything not visible or provided as `unknown / needs confirmation`.

## Information Confidence

Classify every potential selling point before using it:

- `confirmed`: explicitly provided by the user, clearly visible in the product image, or readable on packaging.
- `reasonable inference`: conservative inference from visible form or normal usage; write as general usage fit, not as a hard claim.
- `needs confirmation`: unknown material, size, parameter, efficacy, certification, sales, review, compatibility, ingredient ratio, or authorization.

Use confirmed points first. Use reasonable inference only with conservative wording. Do not place `needs confirmation` facts as on-image claims.

## Product Type Strategy

Choose the strongest strategy for the product:

- `standard / functional product`: emphasize practical function, operation, structure, efficiency, comparison, scenario fit, and confirmable parameters.
- `non-standard / aesthetic product`: emphasize design language, style fit, material texture, visual taste, pairing scenarios, and atmosphere.
- `consumable product`: emphasize taste, texture, usage frequency, preparation, packaging convenience, visible/provided ingredient information, and daily scenario.
- `gift / emotional-value product`: emphasize packaging, ceremony, recipient scenario, display value, atmosphere, and conservative gifting reasons.

If a product spans types, pick the strategy that answers the strongest buyer concern.

## Default Module Page Rhythm

Use this as the default eight-module rhythm. If the `Module Plan` selects 9-12 modules, expand this rhythm without repeating buyer demands or layout structures.

Use this rhythm unless the category playbook, platform profile, reference style, or user request calls for a better structure:

1. `Impact Cover`: strongest purchase reason with category-specific visual motif.
2. `Core Demand`: highest buyer concern with the most direct selling point.
3. `Scene Proof`: realistic use, style, pain-point, or ownership scene.
4. `Detail Evidence`: material, structure, texture, craft, ingredient, interface, or local proof.
5. `Objection Handling`: comparison, annotation, FAQ, problem-solution, or information card.
6. `Use Process`: operation, pairing, wearing, preparing, opening, storing, cleaning, or daily flow.
7. `Info Confirmation`: parameters, visible packaging data, checklist, size, care, package contents, or compatibility caveat.
8. `Closing Summary`: summarize purchase reasons without fake urgency or consultation-style CTA.

If the user requests fewer images, keep cover, core demand, primary proof, scenario fit, and final summary. If the user requests more, expand without repeating page roles.

## Reference Visual Style

When the user provides a reference image, reference detail page, competitor page, or asks to follow a visual style:

- Default to referencing the visual style.
- Extract the overall tone, palette mood, lighting, density, hierarchy, rhythm, visual devices, label/card style, typography feel, and scene atmosphere.
- Rebuild a new `Reference Visual Style Lock` for the current product and platform.
- Learn sales logic and visual direction, but do not copy brand identity, exact page layout, copywriting, logo, certification, review/rating elements, unique ornament, or identifiable design asset.
- If the reference conflicts with visible product truth or platform compliance, adapt the style rather than copying the conflict.

## Screen Frameworks

For each image, define:

- The single buyer demand it answers.
- The matched selling point and information confidence.
- Whether the module is functional proof-driven, aesthetic/design-driven, consumable-driven, or gift/emotional-value-driven.
- Page role and composition for the requested platform and aspect ratio.
- Subject scale: full product, partial crop, local macro, human/object scale, overhead, deep scene, or information card.
- Visual proof method and scene/information structure.
- A short English headline.
- Up to three short support labels.
- Required elements, forbidden elements, and difference from the previous module.

Do not make every image a left-headline/right-product layout. In the planned set, use at least five page structures and at least three subject scales; for 9-12 planned modules, avoid repeating any one structure more than twice.

## Style And Design Locks

Every set must use a consistent visual system:

- `Campaign Style Lock`: broad cross-border campaign direction and platform fit.
- `Reference Visual Style Lock`: only when reference images or competitor pages are provided.
- `Style System Lock`: typography, title hierarchy, label/card system, color system, lighting system, and scene texture.
- `Visual Quality Lock`: product-photography quality, restrained copy, scene depth, material realism, and bans on cheap infographic templates.
- `Design Strength Lock`: category visual motif, buyer-demand rhythm map, composition contrast, signature devices, color contrast, scene density, and template bans.
- `Product Identity & Physics Lock`: product identity traits, structure, material, logo/pattern placement, scale, contact, shadow, occlusion, perspective, and gravity logic, without copying the source photo composition.

Default Campaign Style Lock:

```text
Campaign Style Lock: premium cross-border ecommerce horizontal detail image system; wide 16:9 layout; fixed palette with background, text, accent and divider colors in hex; consistent lighting, typography, icon style, label style, product scale, scene depth, material texture, editorial crop, and purposeful negative space; premium must come from layered design and product desirability, not empty space or decorative gold badges; no fake logo, no watermark, no fake certification, no ratings, no reviews, no discount badges unless provided by user.
```

## Prompt Rules

- Make every prompt standalone.
- Start every image prompt with `wide 16:9 horizontal ecommerce detail module, same size as the full set` unless the user specified another size. In Vertical Marketplace Mode, start with the exact requested canvas such as `vertical 900x1200 Russian Ozon/Wildberries ecommerce detail image`.
- Include the same locks in every prompt.
- Use the uploaded product image only as a product-identity reference, not as a composition reference.
- Preserve the product's visible appearance, color, structure, material look, SKU, and key details.
- If the uploaded product reference is a white-background single-product photo, explicitly forbid recreating it as a white-background single-product image; create a designed ecommerce detail-page composition with buyer-facing copy and visual proof.
- For people/models, include a Model Identity Lock and keep identity, body type, hairstyle, styling logic, and fit stable.
- Use headlines that express buyer benefit, product desire, visual mood, or action, not generic category names.
- Translate parameters into practical context instead of cold specs.
- Show the selling point visually; do not only write it.
- Keep in-image text short, natural, and mobile-readable. Use Russian when the user asks for Russian, Ozon, WB, or Russian marketplaces.
- For Ozon/Wildberries vertical images, use product photography first: one main visual mechanism per image, one headline, two or three selling labels, and at most four necessary parameters. Do not overload the image with cards, icons, measurement lines, and process steps at the same time.
- Avoid fake certifications, fake ratings, fake reviews, fake platform badges, unsupported claims, dense tiny text, and copied competitor layout.
- Avoid cheap blue-white infographic template, PPT card stack, oversized title, repeated three-icon card layout, generic shield icons, fake test badge, and table-like parameter dumping unless the user explicitly asks for a pure specification chart.

## Image Generation

Prefer the Xinghe deployment helper or fixed API route:

- Read `references/fallback-generation.md` before generation.
- Use the deployment image helper first.
- If the helper is missing, use `scripts/generate_image.py` for one image or `scripts/generate_batch.py` for a set when API configuration exists.
- Generate one module per call. For multiple helper calls, submit them with the 3-second staggered concurrent rule before waiting for all outputs.
- Keep the same ratio and style system across all images.
- Use the requested size when the user specifies one; otherwise use `--size 16:9 --resolution 2k`.
- Read API keys from `.env` or environment variables only. Never write real keys into skill files.
- If no API configuration exists or all fixed API routes fail, use built-in `image_gen` as the final fallback.
- If a generated image is meant for the project, copy the selected output into the workspace before final delivery.
- Do not overwrite existing assets unless the user explicitly asks for replacement.

## QA

After generation, check:

- Product consistency with the reference image.
- Physical logic: contact, scale, shadow, occlusion, perspective, hand grip, wearing fit, and scene-object relationships.
- Model consistency when people appear.
- Text legibility and spelling.
- No fake logo, certification, ratings, reviews, platform badges, or unsupported claims.
- All images use the same requested ratio and resolution. Horizontal ratio is required only when the user did not specify a different size.
- Each selling point matches the visual proof.
- The set does not look like a generic template.
- Reference style is adapted without copying competitor identity, exact layout, wording, logo, or unique design assets.
- No more than two modules share the same layout structure.

Default QA is disclosure and selection only. Do not automatically regenerate images unless the user explicitly asks for regeneration.

## Delivery

Use `references/delivery-format.md` for the final response structure.

Default file naming:

```text
product-platform-module-01.png
product-platform-module-02.png
...
```

Preferred folder naming:

```text
<product-name>-crossborder-detail-v1
```

Return:

1. Generation method: Xinghe deployment helper, fixed API script, or built-in `image_gen` final fallback.
2. Save directory.
3. Numbered image list with purpose.
4. QA notes and optional review items.
5. Final kept image count.

Do not create a contact sheet. Contact sheets, preview grids, stitched boards, or any locally assembled image output are disallowed and must never be treated as generated detail-page modules.

## Required Output Sections After Execution

Use these sections when reporting a completed task:

1. Product Image Analysis.
2. Information Confidence.
3. Buyer Demand Map.
4. Demand-to-Selling-Point Match.
5. Product Type Strategy.
6. Platform Profile.
7. Purchase Decision Type.
8. Page Strategy.
9. Best Hero Direction.
10. Module Plan.
11. Visual Rhythm Plan.
12. Reference Visual Style Lock, when references are provided.
13. Campaign Style Lock.
14. Style System Lock.
15. Design Strength Lock.
16. Product Identity & Physics Lock.
17. Page Task Table.
18. Scene Layout Plan.
19. Generation Method.
20. Generated Files.
21. QA Notes / Optional Review Items.

Keep the final answer concise when images have already been generated and saved.
