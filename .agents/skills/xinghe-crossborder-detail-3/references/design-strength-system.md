# Design Strength System

Read this file before direct detail-page image generation. The goal is to avoid generic templates while keeping the output compatible with cross-border PDP, Amazon A+ modules, and user-specified vertical marketplace formats.

## Core Principle

Strong design means every screen has a clear conversion role:

- The opening page needs an immediate purchase reason, not just a centered product.
- A selling-point page should make one buyer demand and one product answer obvious.
- A detail page needs material evidence, structure evidence, craft evidence, texture evidence, or usage evidence.
- A scene page needs realistic use context and physical logic, not a fake background swap.
- An information page should feel like a designed confirmation card, not a spreadsheet screenshot.
- A closing page should summarize purchase reasons, not become a generic CTA.
- A vertical Ozon/WB image should first look like a trustworthy product photograph, then carry concise selling information.

## Design Strength Lock

Before generating a set, write one `Design Strength Lock` and reuse it in every prompt. It must include:

1. `category visual motif`: the most recognizable visual motif for the category and product style.
2. `buyer-demand rhythm map`: the demand progression across the set.
3. `composition contrast`: at least three composition scales across the set, such as wide scene, medium product, human/object scale, extreme close-up, overhead, cutaway, collage, information card, or deep scene perspective.
4. `signature device`: at least two recurring devices, such as material magnifiers, annotation lines, process arrows, environmental props, comparison zones, layered cards, motion trails, cutaway windows, or scene depth.
5. `color contrast`: main color, accent color, dark anchor, highlight color, and readable text zones.
6. `scene density`: purposeful foreground / midground / background layers without meaningless blank space.
7. `template ban`: explicitly ban repeating centered product, top-left title, small labels, pale gradient, and unchanged product scale across the full set.
8. `visual quality rule`: define how product photography, material highlights, scene depth, and restrained copy avoid cheap infographic output.

## Vertical Marketplace Design Strength

Use this when the user requests Ozon/Wildberries, Russian marketplace, Russian copy, or vertical sizes such as `900x1200`.

- Start with product photography: strong product scale, realistic surface contact, real scene depth, and believable lighting.
- Keep text secondary to the product. The product should not feel like an illustration inserted into a slide.
- Use cards only where they help conversion. Cover, scenario, material, stability, and summary pages should not all become blue-white card stacks.
- Reserve measurement lines, diagrams, and process arrows for VESA, size, and installation pages.
- For black metal hardware and TV stands, use restrained technical accents: cool blue highlights, graphite labels, warm wood surface, and soft grey/blue background.
- Do not use the same huge-title + left icon cards + right product rhythm across the set.

## Category Motifs

Choose motifs by product category:

- Sports/outdoor/footwear/apparel: speed lines, track arcs, energy trails, real outdoor ground, fabric movement, body fit, or friction texture.
- Beauty/personal care: texture macro, glossy or matte finish, ingredient still-life, soft light bands, bathroom/vanity scenes, hand-use process, or clean but not empty whitespace.
- Food/beverages: flying ingredients, preparation process, real table scene, steam, liquid flow, serving scene, or origin/ingredient setup.
- Pet products: real home environment, pet interaction, feeding/play process, size relationship, cleaning/storage scene.
- Home/daily-use products: spatial order, before/after comparison, storage modules, hand operation, material close-up, or daily-life flow.
- Electronics/tools: dark technical background, exploded structure, port close-ups, sweeping light, specification card, connection process, or use-scenario desktop.
- Baby/toys: soft care, parent-child daily moments, material close-ups, size relationship, play scene, or storage scene; avoid absolute safety claims.
- Gifts/emotional products: packaging, receiving moment, table display, seasonal setting, ceremony, and warm atmosphere.
- General categories: decide the motif from the product form plus the buyer's main concern; do not default to a generic gradient.

## Cheap Template Ban

Explicitly avoid these phrases and visual patterns in final prompts unless the user asks for a pure spec sheet:

- cheap blue-white infographic template;
- PPT card stack;
- oversized title;
- generic shield icons;
- fake test badge;
- repeated three-icon card layout;
- table-like parameter dumping;
- dense tiny labels;
- small floating product on an empty gradient background.

## Page Rhythm Requirements

In the planned set, include at least:

- five clearly different page structures;
- three subject scales;
- one immersive scene;
- one close-up detail or macro proof page;
- one process, operation, comparison, FAQ, or information card page;
- one summary or collection page.

If the `Module Plan` selects a different count, or the user specifies a different count, compress or expand with the same logic while preserving demand differences, layout differences, and scene evidence.

## Direct Final Image Rule

Final deliverable images must be generated directly by the image tool or API. The only allowed local file handling is downloading, copying, renaming, saving, checking dimensions, and checking file existence. Do not use local scripts to stitch images, overlay text, make collages, replace backgrounds, composite product/background layers, create contact sheets, or crop/recombine images into final deliverables or default preview outputs. If a collage-style page is needed, generate the complete collage-style page directly through the image tool/API.
