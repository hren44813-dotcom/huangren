# Prompt Contract

Each detail-page image must be generated independently. Do not place multiple screens into one image.

## Required Prompt Blocks

Every image prompt must include:

1. The exact user-requested canvas. Use `wide 16:9 horizontal ecommerce detail module, same size as the full set` by default, or `vertical 900x1200 Russian Ozon/Wildberries ecommerce detail image` when the user requests Ozon/WB, Russian marketplace, Russian copy, or vertical `900x1200`.
2. `Campaign Style Lock`: unified cross-border campaign direction, palette, typography feel, background system, lighting, icon style, whitespace logic, and product scale.
3. `Reference Visual Style Lock` when reference images or competitor pages are provided.
4. `Style System Lock`: title hierarchy, label style, information-card style, icon/line style, color system, and lighting system across the whole set.
5. `Design Strength Lock`: category visual motif, page rhythm, composition contrast, signature visual devices, color contrast, and template bans.
6. `Visual Quality Lock`: product-photography quality, product scale, scene depth, restrained copy, material realism, and cheap-template bans.
7. `Product Identity & Physics Lock`: lock product identity traits only: product appearance, packaging, material, proportions, key pattern, logo/nameplate placement, structural-part relationships, scale, contact, shadows, perspective, and occlusion. Do not lock the source photo composition.
8. `Buyer Demand`: the single buyer need, concern, or question solved by this screen.
9. `Matched Selling Point`: one direct selling point that answers the buyer demand.
10. `Information Confidence`: confirmed, reasonable inference, or needs confirmation; never write a needs-confirmation fact as an on-image claim.
11. `Platform Profile`: Amazon A+, Shopify, Temu, AliExpress, TikTok Shop, Ozon/Wildberries, or general cross-border PDP.
12. `Purchase Decision Type`: the selected decision type from the page strategy.
13. `Page Strategy`: the main purchase resistance and conversion angle for the full set.
14. `Module Plan`: module number, module title direction, buyer question, core information, visual suggestion, copy suggestion, required proof, and risk reminder for this screen.
15. Current page role.
16. Current page main title: short natural buyer-facing copy, shown inside the image.
17. Current page selling-point labels or short phrases.
18. Current page visual proof: scene, comparison, action, material macro, structure detail, process flow, information card, texture setup, style pairing, or other proof method.
19. Current page composition and subject scale.
20. Current page difference from the previous page.
21. Negative constraints: do not fabricate sales, certifications, testing, reviews, medical efficacy, parameters, material composition, package quantity, compatibility, brand authorization, or competitor identity.

## Ozon / Wildberries Vertical Prompt Contract

Use this contract when the user requests Ozon/WB, Russian marketplace, Russian copy, or vertical `900x1200`.

Every prompt must include:

- `vertical 900x1200 Russian Ozon/Wildberries ecommerce detail image`, or the exact user-specified vertical size.
- Russian short copy only, unless the user requests another language.
- Product-photography-first composition.
- One main visual mechanism only: product hero, lifestyle scene, material close-up, installation process, VESA card, stability detail, or final checklist.
- One main headline, two to three selling labels, and at most four necessary parameters.
- Product should occupy enough visual area and remain more important than text.
- For hardware and TV stands: black product, warm wood tabletop, light grey/cold blue background, restrained technical accents, realistic metal highlights.

Do not combine cards, icons, measurement lines, arrows, process steps, and multiple diagrams in one image unless the page is explicitly the specification or installation page.

## Product Identity & Physics Lock

Every prompt must reuse the same lock, including:

- `silhouette lock`: preserve overall shape, width/height/depth proportions, and open/closed state.
- `pattern/logo placement lock`: preserve relative position and direction of patterns, logos, nameplates, labels, and visible copy; keep unreadable text as visual placement only and do not invent words.
- `shape/proportion lock`: preserve size relationships between the main body, accessories, base, handles, ports, and decorative parts.
- `color/material lock`: preserve primary color, secondary color, color-area ratio, and visible material appearance.
- `physical logic lock`: preserve believable support, contact, shadow, occlusion, perspective, gravity, hand grip, wearing fit, and scale relationships.
- `do-not-change list`: forbid changing product style, adding unprovided structures, deleting key patterns/nameplates, moving decorative elements, changing the core silhouette, or adding random accessories.
- `composition freedom`: allow and require changes to camera angle, crop, scene, background, props, model display, information layout, typography hierarchy, and page rhythm when they support the current page role.
- `white-background non-replication`: if the uploaded reference is a white-background product photo, explicitly forbid recreating it as a white-background single-product image; convert it into a designed ecommerce detail-page image with headline, selling labels, and visual proof.

Detail, material, craft, and scene pages may omit the full product. When a product crop appears, it must come from the same product and must not become a replacement product from the same category.

## Reference Style Rule

When references are provided, include a `Reference Visual Style Lock` that adapts visual tone, color mood, lighting, density, hierarchy, card/callout style, and scene atmosphere. Do not copy exact layout, wording, logo, brand identity, certification marks, review/rating elements, or unique design assets.

## Design Strength Rule

- Establish and reuse a `Design Strength Lock` and `Style System Lock` for the full prompt set.
- Every image must specify a visual device, subject scale, proof method, and difference from the previous page.
- In a default eight-image set, no more than four images should use a large full-product hero; for 9-12 planned modules, keep full-product hero pages below half of the set.
- Strong design should come from composition, light/shadow, scene depth, material evidence, scale, process, and visual proof, not fabricated selling points.
- In Ozon/WB vertical mode, strong design should look like premium marketplace product photography with restrained information, not a PPT-like infographic.

## Layout Diversity Rule

A default eight-image set must mix at least five structures. For 9-12 planned modules, preserve at least five structures and avoid repeating any one structure more than twice:

- Hero poster.
- Scene immersion.
- Enlarged local detail.
- Material, ingredient, or style flat lay.
- Craft/process flow.
- Parameter, checklist, or specification information card.
- Comparison or objection-handling page.
- FAQ or closing summary.
- Usage process or hand-operation page.
- Category motif page.

Do not make every page follow the same centered-product, top-left-title, bottom-label structure.

## Planned Count Rule

Generate one image for each row in the `Page Task Table`. The final image count must equal the `Module Plan` count unless the user explicitly requested a different count.

Do not output a separate material reshoot list. Missing evidence belongs in module-level risk reminders or final optional review notes.

## Cheap Template Negative Constraints

Add these negative constraints when output quality matters or when generating Ozon/WB vertical images:

```text
Avoid cheap blue-white infographic template, PPT card stack, oversized title, repeated three-icon card layout, generic shield icons, fake test badge, fake certification badge, table-like parameter dumping, dense tiny text, and product pasted onto an empty gradient background.
```
