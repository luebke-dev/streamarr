import { ref, onUnmounted } from 'vue'
import { logger } from 'src/utils/logger'
import { getServerUrl } from 'src/utils/authStorage'

/**
 * Self-contained WebRTC / WebSocket streaming composable for the Lightrays
 * admin test page.  Adapted from lr-frontend/src/composables/useStreaming.js
 * but accepts a configurable `baseUrl` instead of using `location.host`.
 */
export function useLightraysStreaming() {
  // ── Reactive state ──
  const status = ref('idle') // idle | pending | connected | streaming | error
  const statusText = ref('')
  const streaming = ref(false)
  const stats = ref({
    mbps: '0.0',
    fps: 0,
    frames: 0,
    rtt: 0,
    jitter: 0,
    packetsLost: 0,
    resolution: '',
    codec: '',
    decodeTime: 0,
  })

  // ── Internal refs ──
  let ws = null
  let pc = null
  let dataChannel = null
  let pointerLocked = false
  let statsInterval = null
  let videoEl = null
  let streamContainerEl = null
  let currentBaseUrl = ''
  let iceServers = [{ urls: 'stun:stun.l.google.com:19302' }]
  let remoteDescriptionSet = false
  let pendingCandidates = []
  let lastSentResize = { w: 0, h: 0 }

  function setStatus(s, text) {
    status.value = s
    statusText.value = text
  }

  // ── Launch ──
  async function launchApp(baseUrl, appConfig, { width, height, fps, bitrateKbps }) {
    currentBaseUrl = baseUrl.replace(/\/$/, '')
    setStatus('pending', 'Launching…')
    try {
      const res = await fetch(`${currentBaseUrl}/api/launch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          width,
          height,
          fps,
          bitrate_kbps: bitrateKbps,
          title: appConfig.title,
          runtime_profile: appConfig.runtime_profile || 'gow-steam',
          app_id: appConfig.app_id,
          keyboard_layout: appConfig.keyboard_layout,
          start_virtual_compositor: appConfig.start_virtual_compositor,
          start_audio_server: appConfig.start_audio_server,
        }),
      })
      const data = await res.json()
      if (data.error) {
        setStatus('error', data.error)
        return
      }
      if (data.ice_servers && data.ice_servers.length > 0) {
        iceServers = data.ice_servers
      }
      connectWebSocket(
        data.session_id,
        data.ws_ticket || '',
        data.ice_servers || [],
        data.websocket_url || data.ws_url,
      )
    } catch (e) {
      setStatus('error', 'Launch failed: ' + e.message)
      logger.error('Lightrays launch failed:', e)
    }
  }

  // ── WebSocket signaling ──
  let msgQueue = Promise.resolve()

  function connectWebSocket(sid, ticket, iceServersConfig, websocketUrl) {
    if (iceServersConfig && iceServersConfig.length > 0) {
      iceServers = iceServersConfig
    }
    const url = resolveWebSocketUrl(websocketUrl, sid)
    const protocols = ticket ? ['lightrays', ticket] : ['lightrays']
    ws = new WebSocket(url, protocols)

    ws.onopen = () => setStatus('connected', 'Connected — waiting for stream…')

    ws.onmessage = (event) => {
      // Serialize all message handling to prevent race conditions
      msgQueue = msgQueue
        .then(() => processMessage(event))
        .catch((e) => {
          logger.error('Lightrays signaling error:', e)
        })
    }

    ws.onclose = () => {
      if (status.value !== 'error') setStatus('idle', 'Disconnected')
    }

    ws.onerror = (e) => {
      setStatus('error', 'WebSocket error')
      logger.error('Lightrays WebSocket error:', e)
    }
  }

  function resolveWebSocketUrl(websocketUrl, sid) {
    const fallbackPath = `/api/lightrays-ws/${sid}`
    const value = websocketUrl || fallbackPath
    if (value.startsWith('ws://') || value.startsWith('wss://')) {
      return value
    }
    if (value.startsWith('http://') || value.startsWith('https://')) {
      return value.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:')
    }
    const serverUrl = getServerUrl()
    if (serverUrl) {
      const absolute = new URL(value.startsWith('/') ? value : `/${value}`, serverUrl)
      return absolute
        .toString()
        .replace(/^http:/, 'ws:')
        .replace(/^https:/, 'wss:')
    }
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const path = value.startsWith('/') ? value : `/${value}`
    return `${proto}//${location.host}${path}`
  }

  async function processMessage(event) {
    const msg = JSON.parse(event.data)
    if (msg.type === 'offer') {
      await handleOffer(msg.sdp)
    } else if (msg.type === 'ice') {
      const candidate = new RTCIceCandidate({
        candidate: msg.candidate,
        sdpMLineIndex: msg.sdpMLineIndex,
      })
      if (pc && remoteDescriptionSet) {
        await pc.addIceCandidate(candidate)
      } else {
        pendingCandidates.push(candidate)
      }
    } else if (msg.type === 'container_died') {
      setStatus('error', `Container exited (code ${msg.exit_code ?? '?'})`)
      await stopStream(true)
    } else if (msg.error) {
      setStatus('error', msg.error)
    }
  }

  // ── WebRTC ──
  async function handleOffer(sdp) {
    // A fresh offer comes in every time the server rebuilds the WebRTC
    // pipeline (resize, for example). Close the previous peer connection
    // before replacing it — otherwise tracks from the old pipeline keep
    // feeding stale frames into videoEl and the new stream stays black
    // until GC catches up.
    if (pc) {
      try {
        pc.close()
      } catch (e) {
        // PeerConnection close can throw if already closed; safe to ignore
        logger.debug('PeerConnection close threw', e)
      }
      pc = null
    }
    remoteDescriptionSet = false
    pendingCandidates = []
    pc = new RTCPeerConnection({
      iceServers,
    })

    pc.ontrack = (event) => {
      if (!videoEl) return
      if (event.streams?.[0]) {
        videoEl.srcObject = event.streams[0]
      } else {
        const ms = new MediaStream()
        ms.addTrack(event.track)
        videoEl.srcObject = ms
      }
      streaming.value = true
      setStatus('streaming', 'Streaming')
      videoEl.muted = false
      videoEl.play().catch((e) => logger.debug('Autoplay prevented:', e.message))
      startStats()
    }

    pc.ondatachannel = (event) => {
      if (event.channel.label === 'input') {
        dataChannel = event.channel
      }
    }

    pc.onicecandidate = (event) => {
      if (event.candidate && ws?.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({
            type: 'ice',
            candidate: event.candidate.candidate,
            sdpMLineIndex: event.candidate.sdpMLineIndex,
          }),
        )
      }
    }

    pc.oniceconnectionstatechange = () => {
      if (pc.iceConnectionState === 'failed' || pc.iceConnectionState === 'disconnected') {
        setStatus('error', 'Connection lost')
      }
    }

    await pc.setRemoteDescription(new RTCSessionDescription({ type: 'offer', sdp }))
    remoteDescriptionSet = true

    // Drain any ICE candidates that arrived before remote description was set
    for (const c of pendingCandidates) {
      await pc.addIceCandidate(c)
    }
    pendingCandidates = []

    const answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    ws.send(JSON.stringify({ type: 'answer', sdp: answer.sdp }))
  }

  // ── Input ──
  function sendInput(msg) {
    if (dataChannel?.readyState === 'open') {
      dataChannel.send(JSON.stringify(msg))
    } else if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'input', ...msg }))
    }
  }

  function onKeydown(e) {
    if (!streaming.value) return
    if (e.ctrlKey && e.key === 'm') return
    e.preventDefault()
    e.stopPropagation()
    sendInput({ type: 'key', code: e.code, pressed: true })
  }

  function onKeyup(e) {
    if (!streaming.value) return
    if (e.ctrlKey && e.key === 'm') return
    e.preventDefault()
    e.stopPropagation()
    sendInput({ type: 'key', code: e.code, pressed: false })
  }

  function onMousemove(e) {
    if (!videoEl) return
    if (pointerLocked) {
      sendInput({ type: 'mousemove', dx: e.movementX, dy: e.movementY })
    } else {
      // Compute the actual rendered video area within the element
      // (object-fit: contain means black bars may exist)
      const rect = videoEl.getBoundingClientRect()
      const vw = videoEl.videoWidth || 1920
      const vh = videoEl.videoHeight || 1080
      const videoAspect = vw / vh
      const elemAspect = rect.width / rect.height

      let renderW, renderH, offsetX, offsetY
      if (elemAspect > videoAspect) {
        // Pillarboxed (black bars on sides)
        renderH = rect.height
        renderW = rect.height * videoAspect
        offsetX = (rect.width - renderW) / 2
        offsetY = 0
      } else {
        // Letterboxed (black bars top/bottom)
        renderW = rect.width
        renderH = rect.width / videoAspect
        offsetX = 0
        offsetY = (rect.height - renderH) / 2
      }

      const relX = e.clientX - rect.left - offsetX
      const relY = e.clientY - rect.top - offsetY

      // Clamp to video area
      const x = Math.max(0, Math.min(vw, (relX / renderW) * vw))
      const y = Math.max(0, Math.min(vh, (relY / renderH) * vh))

      sendInput({ type: 'mouseabs', x: Math.round(x), y: Math.round(y), w: vw, h: vh })
    }
  }

  function onMousedown(e) {
    e.preventDefault()
    // Auto-capture pointer on first click for seamless mouse control
    if (!pointerLocked && videoEl && !document.pointerLockElement) {
      videoEl.requestPointerLock?.()
    }
    sendInput({ type: 'mousebutton', button: e.button, pressed: true })
  }
  function onMouseup(e) {
    e.preventDefault()
    sendInput({ type: 'mousebutton', button: e.button, pressed: false })
  }
  function onContextmenu(e) {
    e.preventDefault()
  }
  function onWheel(e) {
    e.preventDefault()
    sendInput({ type: 'wheel', dx: e.deltaX, dy: e.deltaY })
  }
  function onPointerlockchange() {
    pointerLocked = document.pointerLockElement === videoEl
  }

  function sendResize(widthPx, heightPx) {
    if (ws?.readyState !== WebSocket.OPEN) return
    // H.264/H.265 encoders need even dimensions; server also rejects <64 or
    // huge values. Server has its own 8-px dead zone, but we guard here too
    // so we don't spam during drag.
    const w = Math.max(64, Math.min(7680, (widthPx + 1) & ~1))
    const h = Math.max(64, Math.min(4320, (heightPx + 1) & ~1))
    if (Math.abs(w - lastSentResize.w) <= 8 && Math.abs(h - lastSentResize.h) <= 8) return
    lastSentResize = { w, h }
    ws.send(JSON.stringify({ type: 'resize', width: w, height: h }))
  }

  // Deliberate, user-initiated re-match of the stream resolution to the
  // current container size. A server-side resize rebuilds the whole WebRTC
  // pipeline (encoder + full ICE renegotiation) and blanks the picture for a
  // few seconds, so — unlike the old automatic path — this only fires when
  // the user explicitly asks for it (toolbar button). Between requests the
  // <video> scales client-side (object-fit: contain), so window/fullscreen
  // changes stay instant.
  function applyResolution() {
    const target = streamContainerEl || videoEl
    if (!target) return
    const dpr = window.devicePixelRatio || 1
    const rect = target.getBoundingClientRect()
    if (rect.width < 1 || rect.height < 1) return
    sendResize(Math.round(rect.width * dpr), Math.round(rect.height * dpr))
  }

  function bindInput(video, container) {
    videoEl = video
    streamContainerEl = container
    document.addEventListener('keydown', onKeydown, true)
    document.addEventListener('keyup', onKeyup, true)
    document.addEventListener('pointerlockchange', onPointerlockchange)
    videoEl?.addEventListener('mousemove', onMousemove)
    videoEl?.addEventListener('mousedown', onMousedown)
    videoEl?.addEventListener('mouseup', onMouseup)
    videoEl?.addEventListener('contextmenu', onContextmenu)
    videoEl?.addEventListener('wheel', onWheel, { passive: false })

    // We deliberately do NOT auto-send a resize on every window / fullscreen
    // change: each server-side resize rebuilds the whole WebRTC pipeline
    // (encoder + full ICE renegotiation) and blanks the picture for seconds.
    // The stream keeps its launch resolution (set from the window size at
    // launch) and the <video> scales client-side, so window changes are
    // instant. The user re-matches native resolution on demand via
    // applyResolution() (toolbar button).
  }

  function unbindInput() {
    document.removeEventListener('keydown', onKeydown, true)
    document.removeEventListener('keyup', onKeyup, true)
    document.removeEventListener('pointerlockchange', onPointerlockchange)
    videoEl?.removeEventListener('mousemove', onMousemove)
    videoEl?.removeEventListener('mousedown', onMousedown)
    videoEl?.removeEventListener('mouseup', onMouseup)
    videoEl?.removeEventListener('contextmenu', onContextmenu)
    videoEl?.removeEventListener('wheel', onWheel)
    lastSentResize = { w: 0, h: 0 }
  }

  // ── Controls ──
  function toggleFullscreen() {
    const el = streamContainerEl || videoEl
    if (!el) return
    document.fullscreenElement
      ? document.exitFullscreen()
      : (el.requestFullscreen?.() ?? el.webkitRequestFullscreen?.())
  }

  function togglePointerLock() {
    pointerLocked ? document.exitPointerLock() : videoEl?.requestPointerLock()
  }

  async function stopStream(keepStatus = false) {
    if (statsInterval) clearInterval(statsInterval)
    if (ws?.readyState === WebSocket.OPEN) {
      ws.close()
    }
    pc?.close()
    pc = null
    dataChannel = null
    remoteDescriptionSet = false
    pendingCandidates = []
    if (videoEl) videoEl.srcObject = null
    streaming.value = false
    document.exitPointerLock?.()
    if (!keepStatus) setStatus('idle', 'Ready')
  }

  // ── Stats ──
  function startStats() {
    if (statsInterval) clearInterval(statsInterval)
    let lastBytes = 0
    let lastTime = performance.now()
    statsInterval = setInterval(async () => {
      if (!pc) return
      try {
        const s = await pc.getStats()
        let rtt = 0
        let jitter = 0
        let packetsLost = 0
        let codec = ''

        s.forEach((report) => {
          if (report.type === 'inbound-rtp' && report.mediaType === 'video') {
            const now = performance.now()
            const dt = (now - lastTime) / 1000
            const bytes = report.bytesReceived || 0
            const bps = dt > 0 ? ((bytes - lastBytes) * 8) / dt : 0
            lastBytes = bytes
            lastTime = now
            jitter = report.jitter || 0
            packetsLost = report.packetsLost || 0

            const res = videoEl ? `${videoEl.videoWidth}x${videoEl.videoHeight}` : ''
            const decodeTime =
              report.totalDecodeTime && report.framesDecoded
                ? ((report.totalDecodeTime / report.framesDecoded) * 1000).toFixed(1)
                : 0

            stats.value = {
              mbps: (bps / 1e6).toFixed(1),
              fps: report.framesPerSecond || 0,
              frames: report.framesDecoded || 0,
              rtt,
              jitter: (jitter * 1000).toFixed(0),
              packetsLost,
              resolution: res,
              codec,
              decodeTime,
            }
          }

          if (report.type === 'candidate-pair' && report.state === 'succeeded') {
            rtt = report.currentRoundTripTime ? (report.currentRoundTripTime * 1000).toFixed(0) : 0
            stats.value.rtt = rtt
          }

          if (report.type === 'codec' && report.mimeType?.includes('video')) {
            codec = report.mimeType.replace('video/', '')
            stats.value.codec = codec
          }
        })
      } catch (e) {
        // Stats collection is best-effort; failures are non-fatal
        logger.debug('WebRTC stats poll failed', e)
      }
    }, 1000)
  }

  onUnmounted(() => {
    unbindInput()
    stopStream()
  })

  return {
    status,
    statusText,
    streaming,
    stats,
    launchApp,
    connectWebSocket,
    bindInput,
    unbindInput,
    applyResolution,
    toggleFullscreen,
    togglePointerLock,
    stopStream,
  }
}
