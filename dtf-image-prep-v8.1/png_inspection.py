"""Read-only PNG inspection. Ghost detection is a spatial heuristic, not proof."""
from pathlib import Path
import math
import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation


def inspect_png(path: Path) -> dict:
    with Image.open(path) as opened:
        dpi = opened.info.get('dpi')
        dpi_text = 'Unknown'
        try:
            x, y = map(float, dpi)
            if all(math.isfinite(v) and v > 0 for v in (x,y)):
                dpi_text = f'{x:.0f}' if abs(x-y)<.05 else f'{x:.0f} × {y:.0f}'
        except (TypeError, ValueError):
            pass
        rgba = opened.convert('RGBA')
        alpha_image = rgba.getchannel('A')
        alpha = np.array(alpha_image)
        alpha_image.close(); rgba.close()
    border = np.concatenate((alpha[0], alpha[-1], alpha[:,0], alpha[:,-1]))
    clear = float(np.mean(border == 0))
    if not np.any(alpha):
        transparency, tone = 'Empty', 'amber'
        transparency_detail = 'All pixels are fully transparent; no visible artwork.'
    elif clear >= .95:
        transparency, tone = '✓ Yes', 'green'
        transparency_detail = f'{clear:.1%} of outer-edge pixels are fully transparent. This does not prove every interior background area is clear.'
    elif np.any(alpha < 255):
        transparency, tone = 'Partial', 'amber'
        transparency_detail = f'Contains transparency, but only {clear:.1%} of outer-edge pixels are fully transparent. Artwork may touch the edge, or background may remain.'
    else:
        transparency, tone = '✕ No', 'red'
        transparency_detail = 'All pixels are fully opaque; there is no transparent background.'
    strong = alpha > 30
    if not np.any(strong) and np.any(alpha):
        ghost, ghost_tone, ghost_detail = 'Review', 'amber', 'Image is entirely faint (alpha ≤30); cannot distinguish intentional artwork from ghost pixels.'
    else:
        # Faint pixels farther than 10 pixels (square neighborhood) from stronger
        # artwork are suspicious. Soft edges close to artwork are not flagged.
        near = binary_dilation(strong, structure=np.ones((3,3),bool), iterations=10)
        suspect = (alpha > 0) & (alpha <= 30) & ~near
        count = int(np.count_nonzero(suspect))
        flagged = count >= 5
        ghost = '✓ Possible' if flagged else '— None found'
        ghost_tone = 'amber' if flagged else 'green'
        ghost_detail = (f'{count:,} faint pixels (alpha 1–30) more than 10 pixels from stronger artwork. '
                        'Five or more triggers a flag. Intentional faint details can also trigger it; '
                        'no flag does not guarantee every stray pixel is absent.')
    return dict(transparency=transparency, transparency_tone=tone,
                transparency_detail=transparency_detail, ghost=ghost,
                ghost_tone=ghost_tone, ghost_detail=ghost_detail, dpi=dpi_text)
