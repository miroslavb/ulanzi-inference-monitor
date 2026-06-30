// layout.js — key-id helpers.
//
// The host key id is "col_row". On the D200H this value can be unstable/duplicated
// across the device, so it is used ONLY as a best-effort default cell position
// (locked on first sight); it is NOT used to group keys. Each key renders
// independently in app.js, which is immune to id flips and duplicates.

export function parseKey(key) {
  const parts = String(key).split('_');
  const col = parseInt(parts[0], 10);
  const row = parseInt(parts[1], 10);
  return { col: Number.isFinite(col) ? col : 0, row: Number.isFinite(row) ? row : 0 };
}
