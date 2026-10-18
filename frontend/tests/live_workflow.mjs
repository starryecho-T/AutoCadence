// Explicit opt-in: this workflow creates a real Cadence simulation.
if (!process.env.VAI_LIVE_URL && !process.argv.includes('--live')) throw new Error('Pass --live to run a real remote simulation.')
await import('./general_live_workflow.mjs')
