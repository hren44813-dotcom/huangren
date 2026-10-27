# QA Checklist

## No Auto-Regeneration Rule

Do not automatically regenerate after QA. QA should disclose issues and risk level only. Deliver the generated set unless the user explicitly asks for regeneration, redo, re-create, fix, or replacement.

## Must Check

- Product matches reference image in shape, color, major structure, material appearance, pattern/logo/nameplate placement, and visible details.
- Physical logic is believable: contact, scale, shadow, occlusion, perspective, gravity, hand grip, wearing fit, and scene-object relationships.
- If a model appears, the same model identity, body type, hairstyle, and styling logic are maintained across the set.
- Every image in the set is horizontal `16:9` unless the user explicitly requested another ratio.
- Every image in the set uses the same ratio and resolution.
- No fake logo, fake certification, fake ratings, fake review quotes, fake marketplace badges, fake tests, or unsupported claims.
- No unsupported material composition, medical claim, safety claim, waterproof claim, compatibility list, or guarantee.
- Text is readable, short, natural English unless otherwise requested, and not misspelled.
- For Russian marketplace images, Russian copy is short, readable, natural, and does not overlap or overpower the product.
- Each image answers one buyer demand and one matched selling point.
- The visual proof matches the written benefit.
- Premium or high-end styling is supported by visible design layers: product scale, lighting depth, material texture, foreground/background relationship, editorial crop, or scene structure.
- Ozon/Wildberries vertical images feel like product photography with restrained selling information, not low-price parameter posters.
- Reference visual style is adapted without copying competitor brand, logo, exact layout, wording, certification marks, ratings/reviews, or unique design assets.

## Flag As High Risk If

- The product changes category, color, structure, material, logo/nameplate placement, or key visible details.
- The output is vertical, square, or a mismatched size in a horizontal set.
- Text is garbled or too dense.
- A branded prop appears and could be mistaken as a claim or affiliation.
- The image becomes a pure product photo with no ecommerce information structure.
- A high-risk claim appears without user-provided proof.
- The image looks like a generic template instead of strong commercial design.
- The image looks like a cheap blue-white infographic template, PPT card stack, or repeated three-icon parameter page.
- The title is oversized and dominates the product.
- The image lacks realistic scene light, material highlights, contact shadows, or product photography quality.
- The image relies mainly on blank space, gold labels, badge circles, beige icon rows, or a small floating product to appear premium.
- More than two modules share the same layout rhythm.
- A reference or competitor page is copied too closely.

## Safer Alternatives For Future Prompts

- Use product-only / ghost mannequin if model identity fails.
- Use labels instead of long body copy if text accuracy is weak.
- Use `proof placeholder` or omit trust badges when proof is missing.
- Use generic props without logos.
- Use a shorter prompt while preserving Campaign Style Lock, Style System Lock, Design Strength Lock, and Product Identity & Physics Lock when generation fails.
- For Ozon/WB images, reduce to one headline, two labels, one strong product-photo scene, and one visual mechanism.
