const dot = document.getElementById('dot') as HTMLSpanElement
const label = document.getElementById('label') as HTMLSpanElement

window.iris?.onIndicatorState((state) => {
  if (state.screen) {
    dot.className = 'dot screen'
    label.textContent = 'capture d’écran'
  } else if (state.mic) {
    dot.className = 'dot'
    label.textContent = state.listening ? 'micro actif — écoute' : 'micro actif'
  } else if (state.camera) {
    dot.className = 'dot'
    label.textContent = 'caméra active'
  } else {
    label.textContent = 'capture terminée'
  }
})
