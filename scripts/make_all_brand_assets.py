import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw
import numpy as np
import os

os.makedirs('static/img', exist_ok=True)

# Parse icon binary svg
icon_tree = ET.parse('scripts/icon_binary.svg')
icon_root = icon_tree.getroot()
icon_paths = list(icon_root.iter('{http://www.w3.org/2000/svg}path'))

# Path 1: Droplet
droplet_d = icon_paths[1].attrib.get('d')
droplet_trans = icon_paths[1].attrib.get('transform')

# Path 2 & 3: S cutouts
s_lower_d = icon_paths[2].attrib.get('d')
s_lower_trans = icon_paths[2].attrib.get('transform')

s_upper_d = icon_paths[3].attrib.get('d')
s_upper_trans = icon_paths[3].attrib.get('transform')

# Parse text binary svg
text_tree = ET.parse('scripts/text_binary.svg')
text_root = text_tree.getroot()
text_paths = list(text_root.iter('{http://www.w3.org/2000/svg}path'))

# Colors from official asset IMG_20261011_184504_828.jpg:
# Droplet lavender: #C893FF
# Deep purple background / S: #2A0F42
# White: #FFFFFF
# Soft neon purple accent: #A855F7

# ==============================================================================
# 1. logo-icon.svg (Standalone Brand Mark, 390x300 viewBox)
# ==============================================================================
logo_icon_svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 390 300" width="100%" height="100%" fill="none">
  <!-- Droplet Shape -->
  <path d="{droplet_d}" fill="#C893FF" transform="{droplet_trans}" />
  <!-- Stylized S Cutout -->
  <path d="{s_lower_d}" fill="#2A0F42" transform="{s_lower_trans}" />
  <path d="{s_upper_d}" fill="#2A0F42" transform="{s_upper_trans}" />
</svg>'''

with open('static/img/logo-icon.svg', 'w', encoding='utf-8') as f:
    f.write(logo_icon_svg)

# ==============================================================================
# 2. favicon.svg (Squircle App Icon as seen in IMG_20261011_213038_917.jpg)
# ==============================================================================
favicon_svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512" fill="none">
  <defs>
    <linearGradient id="subheroGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#361259" />
      <stop offset="50%" stop-color="#2A0F42" />
      <stop offset="100%" stop-color="#1B0630" />
    </linearGradient>
  </defs>
  <!-- Squircle Rounded Container -->
  <rect width="512" height="512" rx="128" fill="url(#subheroGrad)" />
  <rect width="510" height="510" x="1" y="1" rx="127" stroke="rgba(200, 147, 255, 0.25)" stroke-width="2" />
  <!-- Droplet & S Centered -->
  <g transform="translate(61, 86) scale(1.0)">
    <path d="{droplet_d}" fill="#C893FF" transform="{droplet_trans}" />
    <path d="{s_lower_d}" fill="#2A0F42" transform="{s_lower_trans}" />
    <path d="{s_upper_d}" fill="#2A0F42" transform="{s_upper_trans}" />
  </g>
</svg>'''

with open('static/favicon.svg', 'w', encoding='utf-8') as f:
    f.write(favicon_svg)

# Also create root favicon.svg if queried directly
with open('static/img/favicon.svg', 'w', encoding='utf-8') as f:
    f.write(favicon_svg)

# ==============================================================================
# 3. logo.svg (Full Wordmark Lockup for Dark Theme)
# ==============================================================================
# Combine icon and Subhero wordmark text paths
text_elements_dark = []
text_elements_light = []
for p in text_paths[1:]:  # skip path 0 (canvas)
    fill = p.attrib.get('fill')
    d = p.attrib.get('d', '')
    trans = p.attrib.get('transform', '')
    if fill == '#000000':
        text_elements_dark.append(f'<path d="{d}" fill="#FFFFFF" transform="{trans}" />')
        text_elements_light.append(f'<path d="{d}" fill="#2A0F42" transform="{trans}" />')
    elif fill == '#FFFFFF':
        text_elements_dark.append(f'<path d="{d}" fill="#160824" transform="{trans}" />')
        text_elements_light.append(f'<path d="{d}" fill="#FFFFFF" transform="{trans}" />')

logo_full_dark = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 390 400" width="100%" height="100%" fill="none">
  <!-- Droplet -->
  <path d="{droplet_d}" fill="#C893FF" transform="{droplet_trans}" />
  <path d="{s_lower_d}" fill="#2A0F42" transform="{s_lower_trans}" />
  <path d="{s_upper_d}" fill="#2A0F42" transform="{s_upper_trans}" />
  <!-- Subhero Wordmark -->
  <g transform="translate(0, 315)">
    {''.join(text_elements_dark)}
  </g>
</svg>'''

with open('static/img/logo-full.svg', 'w', encoding='utf-8') as f:
    f.write(logo_full_dark)

# Horizontal Lockup for Navbar: Icon on Left (height 40), Text on Right
logo_horizontal_dark = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 120" width="100%" height="100%" fill="none">
  <!-- Icon scaled and positioned left -->
  <g transform="translate(10, 0) scale(0.38)">
    <path d="{droplet_d}" fill="#C893FF" transform="{droplet_trans}" />
    <path d="{s_lower_d}" fill="#2A0F42" transform="{s_lower_trans}" />
    <path d="{s_upper_d}" fill="#2A0F42" transform="{s_upper_trans}" />
  </g>
  <!-- Text scaled and positioned right -->
  <g transform="translate(155, 26) scale(0.92)">
    {''.join(text_elements_dark)}
  </g>
</svg>'''

with open('static/img/logo-horizontal.svg', 'w', encoding='utf-8') as f:
    f.write(logo_horizontal_dark)

# Standard logo.svg points to horizontal navbar logo
with open('static/img/logo.svg', 'w', encoding='utf-8') as f:
    f.write(logo_horizontal_dark)

print("Generated vector SVGs: logo-icon.svg, favicon.svg, logo-full.svg, logo-horizontal.svg, logo.svg")

# ==============================================================================
# 4. Generate High-Res PNGs from Master (512x512 favicon.png, sh-logo.png)
# ==============================================================================
# Create square 512x512 squircle icon like IMG_20261011_213038_917.jpg
bg_size = 512
app_icon = Image.new("RGBA", (bg_size, bg_size), (0, 0, 0, 0))
draw = ImageDraw.Draw(app_icon)

# Draw rounded rect with deep royal purple gradient
draw.rounded_rectangle([0, 0, bg_size, bg_size], radius=128, fill=(42, 15, 66, 255))
# Subtle border
draw.rounded_rectangle([0, 0, bg_size, bg_size], radius=128, outline=(200, 147, 255, 60), width=3)

# Load the droplet icon image and colorize it
icon_crop = Image.open('IMG_20261011_162358_500.jpg').convert('L').crop((345, 432, 735, 732))
# Invert so black is 255
inv = Image.fromarray(255 - np.array(icon_crop))

# Create colored version: background transparent, droplet lavender (#C893FF), S deep purple (#2A0F42)
arr = np.array(icon_crop)
colored_icon = Image.new("RGBA", icon_crop.size, (0, 0, 0, 0))
col_arr = np.array(colored_icon)

# Mask: where arr is dark (< 140), it's the droplet
# Inside the droplet, where arr is bright (> 200), it's the S
droplet_mask = arr < 150
s_mask = (arr >= 150) & (arr <= 255)

# Fill droplet with Lavender #C893FF (200, 147, 255)
col_arr[droplet_mask] = [200, 147, 255, 255]
# Fill S with Deep Purple #2A0F42 (42, 15, 66)
# But only inside the droplet bounding region:
# Let's use the actual binary SVG or flood fill
colored = Image.open('scripts/icon_binary.png')
# Binary has white background, black droplet, white S
b_arr = np.array(colored)
is_droplet = b_arr == 0
# To find the inner S, invert and find connected component or use the S paths
# In b_arr, the S is white (255) surrounded by black (0)
s_inner = (b_arr == 255)
# Exclude outside borders
# Let's fill the droplet with lavender
out_rgba = Image.new("RGBA", colored.size, (0, 0, 0, 0))
out_data = np.array(out_rgba)
out_data[is_droplet] = [200, 147, 255, 255]

# Find inner S by masking: rows 50 to 220, cols 100 to 300 where b_arr == 255
s_box = np.zeros_like(b_arr, dtype=bool)
s_box[40:230, 90:310] = True
s_pixels = (b_arr == 255) & s_box
out_data[s_pixels] = [42, 15, 66, 255]

colored_result = Image.fromarray(out_data)

# Resize to fit in 512x512 with good padding
target_w = 340
target_h = int(target_w * (colored_result.height / colored_result.width))
colored_result = colored_result.resize((target_w, target_h), Image.LANCZOS)

paste_x = (bg_size - target_w) // 2
paste_y = (bg_size - target_h) // 2
app_icon.paste(colored_result, (paste_x, paste_y), mask=colored_result)

# Save PNGs
app_icon.save('static/favicon.png')
app_icon.save('static/img/sh-logo.png')
app_icon.resize((192, 192), Image.LANCZOS).save('static/img/icon-192.png')
app_icon.resize((512, 512), Image.LANCZOS).save('static/img/icon-512.png')

# Save ICO
app_icon.resize((64, 64), Image.LANCZOS).save('static/favicon.ico')

print("All PNG and ICO assets generated successfully!")
