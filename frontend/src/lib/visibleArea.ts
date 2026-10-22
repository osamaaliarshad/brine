export type Area = { top: number; right: number; bottom: number; left: number }

/**
 * Where something hanging off `el` (a popup or menu) can be seen: the window, less what any
 * ancestor that cuts off its overflow leaves out (a card with overflow-hidden, the scrolling page
 * beside the sidebar).
 */
export function visibleArea(el: Element): Area {
  const area: Area = { top: 0, right: window.innerWidth, bottom: window.innerHeight, left: 0 }
  for (let a = el.parentElement; a; a = a.parentElement) {
    const { overflowX, overflowY } = getComputedStyle(a)
    if (overflowX === 'visible' && overflowY === 'visible') continue
    const rect = a.getBoundingClientRect()
    if (overflowY !== 'visible') {
      area.top = Math.max(area.top, rect.top)
      area.bottom = Math.min(area.bottom, rect.bottom)
    }
    if (overflowX !== 'visible') {
      area.left = Math.max(area.left, rect.left)
      area.right = Math.min(area.right, rect.right)
    }
  }
  return area
}
