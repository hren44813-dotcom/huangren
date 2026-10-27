# Product Consistency & Physics

Use this file before prompt writing and reuse one `Product Identity & Physics Lock` in every prompt.

Product consistency means locking product identity, not locking the original photo composition. Product reference images define the product's visible identity only. They do not define the final image background, camera angle, cropping, lighting setup, product placement, model presentation, scene, or ecommerce detail-page layout.

## Product Identity & Physics Lock

The lock must include:

- silhouette, proportions, open/closed state, and volume relationships;
- color-area ratio, material appearance, transparency, reflectivity, textile, cream, metal, plastic, paper, food texture, or other visible material cues;
- pattern, logo, label, nameplate, decorative element, and visible-copy placement;
- structural relationships such as handles, caps, lids, ports, zippers, seams, buttons, bases, stands, straps, or accessories;
- product scale relative to hands, body, table, shelf, pet, bag, cup, room, or other scene objects;
- contact, shadow, occlusion, perspective, gravity, and light-source direction rules.

The final detail-page image may change composition, angle, camera distance, crop, scene, props, model display, information layout, typography hierarchy, and page rhythm as long as the product's identity traits above remain recognizable and physically plausible.

## Reference Photo Non-Replication Rule

Reference photos must not be copied as final page layouts. If a reference product photo is a white-background single-product image, explicitly transform it into an ecommerce detail-page composition with buyer-facing copy, visual proof, scene/design structure, and a different camera/composition choice.

Every prompt using a white-background product reference must include:

```text
Use the reference image only to lock product identity. Do not replicate the white-background product photo as a white-background single-product image. Change the composition, angle, crop, scene or detail-page layout, and add the required ecommerce headline, selling labels, and visual proof.
```

## No Product Drift

Do not change the product into another item from the same category. Do not add unprovided accessories, ports, colors, patterns, package counts, components, or functions. Do not delete key structures or move decorative elements.

## Physical Space Logic

Scene pages must obey real physical logic:

- the product must rest on, hang from, be held by, be worn by, or be placed in the scene with believable contact;
- shadows must match the product position and light direction;
- occlusion must be plausible when hands, props, furniture, pets, models, or packaging overlap the product;
- perspective and scale must stay stable across objects;
- reflective, transparent, metal, textile, liquid, powder, and food materials must behave consistently;
- human hands, model poses, pet interaction, and wearable fit must not be twisted, misaligned, floating, or impossible.

## Detail Crop Rule

Close-up pages may omit the full product, but the crop must look like it comes from the same product. Local details must preserve material, color ratio, structure, pattern, and placement logic from the reference.

## Wearable And Model Rule

For apparel, footwear, bags, accessories, and wearable products:

- keep the same person identity, body type, hairstyle, styling logic, and fit when reference images include a model;
- show believable wearing, carrying, folding, drape, straps, seams, closures, and body contact;
- avoid impossible fabric behavior, wrong limb positions, or floating accessories.
