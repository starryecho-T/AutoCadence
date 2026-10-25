/** 下一次查询在上一次结束后开始；出错按 1.5s→3s→6s 退避重试（至多 3 次，成功即重置），停止时取消请求并丢弃迟到的响应。 */
export function pollSequentially<T>(options: {
  read: (signal: AbortSignal) => Promise<T>
  onValue: (value: T) => void
  isDone: (value: T) => boolean
  onError: (error: unknown) => void
  intervalMs: number
}): () => void {
  const controller = new AbortController()
  const backoffMs = [1500, 3000, 6000]
  let timer: ReturnType<typeof setTimeout> | undefined
  let failures = 0
  async function tick() {
    try {
      const value = await options.read(controller.signal)
      if (controller.signal.aborted) return
      options.onValue(value)
      failures = 0
      if (!options.isDone(value) && !controller.signal.aborted) timer = setTimeout(tick, options.intervalMs)
    } catch (error) {
      if (controller.signal.aborted) return
      options.onError(error)
      if (failures < backoffMs.length && !controller.signal.aborted) timer = setTimeout(tick, backoffMs[failures++])
    }
  }
  void tick()
  return () => { controller.abort(); clearTimeout(timer) }
}
