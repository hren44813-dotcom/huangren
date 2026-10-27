# Prompt Templates

Use these templates to stabilize output. Replace bracketed fields. Keep `wide 16:9` and the same locks in every prompt.

## Universal Module Prompt

```text
[Use exact requested canvas. Default: wide 16:9 horizontal ecommerce detail module, same size as the full set. For Ozon/Wildberries / Russian marketplace / 900x1200 requests: vertical 900x1200 Russian Ozon/Wildberries ecommerce detail image.]

[Campaign Style Lock]
[Reference Visual Style Lock, when reference images or competitor detail pages are provided]
[Style System Lock]
[Design Strength Lock]
[Visual Quality Lock]
[Product Identity & Physics Lock]
[Optional Model Identity Lock]

Use the uploaded product image only as a product-identity reference, not as a composition reference.
Preserve the visible product appearance, color, packaging, structure, material look, SKU, logo/nameplate placement, pattern placement, proportions, and key details.
Do not replicate a white-background reference as a white-background single-product image. Change the composition, angle, crop, scene or detail-page layout, and include the required ecommerce headline, selling labels, and visual proof.

Create module [NN] of [TOTAL] for a cross-border ecommerce detail page.
Platform profile: [Amazon A+ / Shopify / Temu / AliExpress / TikTok Shop / general cross-border PDP].
Purchase decision type: [impulse-driven / efficacy-driven / trust-driven / aesthetic-driven / parameter-driven / gift-driven].
Page strategy: [main purchase resistance and conversion angle].
Page role: [impact cover / core demand / scene proof / detail evidence / objection handling / use process / info confirmation / closing summary].
Module plan: [module title direction, buyer question, core information, visual suggestion, copy suggestion, required proof, risk reminder].
Buyer demand: [one buyer question or concern this image answers].
Matched selling point: [one selling point that answers the demand].
Information confidence: [confirmed / reasonable inference / needs confirmation]. Do not write needs-confirmation facts as on-image claims.
Product type strategy: [standard-functional / aesthetic-design / consumable / gift-emotional-value / mixed].

Headline text: "[short natural English headline]"
Support labels: "[label 1]" / "[label 2]" / "[label 3]"
Composition and subject scale: [wide scene / full product / partial crop / local macro / human-object scale / overhead / information card], product or key material detail uses a clear scale appropriate for this module.
Visual proof: [what the image should show, not just say].
Scene/information structure: [foreground / midground / background or card/callout/process structure].
Difference from previous module: [change background system, subject scale, title position, product angle, visual device, or information density].
Required elements: [must appear].
Forbidden elements: [must not appear].

Avoid: fake logo, watermark, fake certification, fake reviews, fake ratings, fake platform badge, unsupported claims, dense tiny text, distorted product, copied competitor layout, copied competitor wording, copied brand assets, small floating product on a large empty background, gold badge circles, beige icon rows, fake luxury frames.
```

## Ozon / Wildberries Vertical Template

```text
vertical 900x1200 Russian Ozon/Wildberries ecommerce detail image, or exact user-specified vertical size.

[Campaign Style Lock: use Ozon / Wildberries Vertical Hardware when appropriate]
[Style System Lock]
[Visual Quality Lock]
[Design Strength Lock]
[Product Identity & Physics Lock]

Use the uploaded product image only as a product-identity reference, not as a composition reference.
Preserve product silhouette, structure, material, color, part relationships, contact shadows, and scale.
Do not replicate a white-background reference as a white-background single-product image. Change the composition, angle, crop, scene or detail-page layout, and include the required ecommerce headline, selling labels, and visual proof.

Create module [NN] of [TOTAL].
Page role: [product-photography cover / size fit / VESA compatibility / material close-up / tabletop placement / stability detail / scenario / final checklist].
Purchase decision type: [impulse-driven / efficacy-driven / trust-driven / aesthetic-driven / parameter-driven / gift-driven].
Page strategy: [main purchase resistance and conversion angle].
Module plan: [module title direction, buyer question, core information, visual suggestion, copy suggestion, required proof, risk reminder].
Buyer demand: [one buyer question].
Matched selling point: [one selling point].
Information confidence: [confirmed / reasonable inference / needs confirmation].

Russian headline: "[short headline]"
Russian labels: "[label 1]" / "[label 2]" / "[label 3]"
Visual mechanism: choose only one primary mechanism for this image.
Composition: product photography first; product should dominate; text must be secondary and readable.
Scene: realistic home/office/tabletop or clean studio-home scene with believable light and shadows.

Avoid: cheap blue-white infographic template, PPT card stack, oversized title, repeated three-icon card layout, generic shield icons, fake test badge, fake certification badge, Ozon/WB logo, fake reviews, fake ratings, table-like parameter dumping, dense tiny text, invented product parts, invented ports, invented screw counts, invented stress-test scene.
```

## Default 8 Module Names

Use these names only as the default rhythm. If the `Module Plan` contains a different count, generate one prompt per planned module and adapt the role names accordingly.

1. Impact cover
2. Core demand
3. Scene proof
4. Detail evidence
5. Objection handling
6. Use process
7. Info confirmation
8. Closing summary

## Text Rules

- Headline: 3-8 English words.
- Support labels: up to 3 labels, 1-4 words each.
- Body copy: avoid unless necessary; one short line max.
- If text rendering fails, use fewer labels and simple icons instead of paragraphs.
