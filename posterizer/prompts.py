"""
Default text shown to customers beside the ready-image upload.

Kept here rather than inline in models.py so the wording stays easy to find and
edit. It is only a *default*: admins can rewrite it in the admin panel, and
doing so takes effect immediately without a deploy.
"""

DEFAULT_AI_PROMPT = """\
Transform the attached image into a stylized geometric portrait. First, strictly isolate the subject and replace the original background with a completely solid, uniform, flat-color background (e.g., pure white or bright contrasting color) to create maximum visual contrast. Ensure the background color is entirely distinct and does not blend or bleed into the subject’s face or clothing.

Art Style & Technique: Extreme posterization, flat vector illustration, low poly art style, geometric color blocking.

Colors & Shading: Monochromatic/Duotone color palette (limited to exactly 4 or 5 distinct solid shades, e.g., navy blue, royal blue, light blue, and pure white). Absolutely NO gradients, NO soft blending, NO continuous tones, and NO photorealism. Every shadow, mid-tone, and highlight must be converted into a flat, solid color.

Shapes & Details: Lighting and facial features must be defined by sharply edged, distinct geometric polygons and hard vector shapes. Crisp lines, stencil art aesthetic, high-contrast screen-print style, minimalist graphic design, crisp vector graphics, masterpiece, 8k resolution vector art.
"""
