// ============================================
// OmniCast Engine — Character Sprite Module
// --------------------------------------------
// Renders the 2D pixel-art character sprites using the sprite sheets
// copied from the Free folder (Idle, Walking, Running).
// Supports role color hue-rotation filters and directional walk cycles.
// ============================================

function renderCharacter(species, color, action = 'idle', direction = 'up') {
  // Map hex color code back to role color name for CSS class binding
  let colorName = 'blue';
  if (color) {
    const hexMap = {
      '#22c55e': 'green',
      '#3b82f6': 'blue',
      '#ef4444': 'red',
      '#a855f7': 'purple',
      '#f59e0b': 'amber',
      '#94a3b8': 'gray',
    };
    if (hexMap[color]) {
      colorName = hexMap[color];
    } else {
      colorName = String(color).toLowerCase();
    }
  }

  // Map directions to css-friendly keys
  let dirKey = 'up';
  if (direction === 'down' || direction === 'south') dirKey = 'down';
  else if (direction === 'left' || direction === 'west') dirKey = 'left';
  else if (direction === 'right' || direction === 'east') dirKey = 'right';
  else dirKey = 'up';

  // Map actions to css-friendly keys
  let actKey = 'idle';
  if (action === 'walk' || action === 'walking') actKey = 'walk';
  else if (action === 'run' || action === 'running') actKey = 'run';
  else actKey = 'idle';

  return (
    <div className={`sprite-agent sprite-${actKey} dir-${dirKey} hue-${colorName}`}></div>
  );
}

Object.assign(window, { renderCharacter });
