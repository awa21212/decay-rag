// dsh-rag-memory (package name: dsh-preflight)
//
// Two capabilities, both backed by the user's own local RAG:
//   1. before each agent step, retrieve notes relevant to the latest user
//      message and append them as an extra user message ("<preflight>…");
//   2. a `rag_search` tool, so the model can search the same library again
//      with different wording mid-task.
//
// Everything is fail-safe: any error returns the step decision unchanged, and
// the tool returns a plain error string instead of throwing.

import { spawn } from 'node:child_process'

const DEFAULTS = {
  enabled: true,
  // Portable defaults: `python` resolves from PATH, and `script`/`cwd` must be
  // set in cordis.patch.yml (point them at four_corpus/preflight.py in this repo).
  python: 'python',
  script: '',
  cwd: '',
  // steps
  inject: true,
  k: 3,
  timeoutMs: 12000,
  maxChars: 1400,
  minQueryChars: 2,
  skipPrefixes: ['/', '!'],
  // tool
  tool: true,
  toolK: 4,
  toolTimeoutMs: 20000,
  toolMaxChars: 8000,
}

const USER_SOURCE_KIND = 'user'
const SOURCE_KIND = 'preflight'

function textOf(message) {
  if (!message || !Array.isArray(message.content)) return ''
  return message.content
    .map((block) => (block && block.type === 'text' && typeof block.text === 'string' ? block.text : ''))
    .join('\n')
    .trim()
}

function lastUserText(messages) {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i]
    if (!message || !message.source || message.source.kind !== USER_SOURCE_KIND) continue
    const text = textOf(message)
    if (text) return text
  }
  return ''
}

/** Run the local retrieval script and resolve with its stdout (empty on failure). */
function runPreflight(config, query, extraArgs, timeoutMs, signal) {
  return new Promise((resolve) => {
    let settled = false
    const done = (value) => {
      if (settled) return
      settled = true
      resolve(value)
    }
    let child
    try {
      child = spawn(config.python, [config.script, query, ...extraArgs], {
        cwd: config.cwd,
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
      })
    } catch {
      done('')
      return
    }
    let out = ''
    let err = ''
    const timer = setTimeout(() => {
      try { child.kill() } catch {}
      done(out)
    }, timeoutMs)
    child.stdout.on('data', (chunk) => {
      out += chunk.toString('utf8')
      if (out.length > 200000) out = out.slice(0, 200000)
    })
    child.stderr.on('data', (chunk) => {
      err += chunk.toString('utf8')
      if (err.length > 4000) err = err.slice(0, 4000)
    })
    child.on('error', () => { clearTimeout(timer); done('') })
    child.on('close', (code) => {
      clearTimeout(timer)
      if (code === 0) done(out)
      else done(err ? `${out}\n[exit ${code}] ${err.trim().split('\n').slice(-3).join(' | ')}` : out)
    })
    if (signal && typeof signal.addEventListener === 'function') {
      signal.addEventListener('abort', () => {
        try { child.kill() } catch {}
        clearTimeout(timer)
        done(out)
      }, { once: true })
    }
  })
}

function clamp(text, max) {
  if (typeof text !== 'string') return ''
  return text.length > max ? `${text.slice(0, max)}\n…（截断，共 ${text.length} 字）` : text
}

function buildInjection(text, config, createUserMessage) {
  const body = clamp(text, config.maxChars)
  const content = [
    {
      type: 'text',
      text:
        '<preflight>\n本次任务相关的既往经验（本地方法库检索，读一遍再动手；没有命中就照常做）:\n'
        + body
        + '\n</preflight>',
    },
  ]
  if (typeof createUserMessage === 'function') {
    try {
      return createUserMessage({ content, source: { kind: SOURCE_KIND } })
    } catch {}
  }
  return { role: 'user', content, source: { kind: SOURCE_KIND } }
}

/** Registry-ready definition, built without importing @deepseek-ai/dsh-tools. */
function buildRagSearchTool(config) {
  return {
    name: 'rag_search',
    description:
      'Search the local method library (the user\'s own notes: code lessons, finance/factor notes, task state, diary). '
      + 'Returns the best-matching blocks with scores. Use it to recover earlier decisions, mistakes and environment '
      + 'facts that are not in the current context; rephrase the query rather than repeating one that returned nothing useful.',
    parameters: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'What you are looking for, in natural language or keywords. Chinese and English both work.',
        },
        k: {
          type: 'number',
          description: `How many blocks to return. Default ${config.toolK}; more than 10 is clipped.`,
        },
        corpora: {
          type: 'string',
          description:
            'Comma-separated corpora: code, finance, task, life. Default "code,finance,task". '
            + 'Add "life" only for questions about the user\'s diary, chats or daily life.',
        },
        full: {
          type: 'boolean',
          description: 'Return each block in full instead of the first 240 characters. Default false.',
        },
      },
      required: ['query'],
      additionalProperties: false,
    },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: String(value ?? '') }],
    },
    async execute(args, exec) {
      const query = typeof args?.query === 'string' ? args.query.trim() : ''
      if (!query) return 'rag_search: empty query.'
      const rawK = Number(args?.k)
      const k = Number.isFinite(rawK) && rawK > 0 ? Math.min(Math.floor(rawK), 10) : config.toolK
      const extra = []
      if (k) extra.push('-k', String(k))
      const corpora = typeof args?.corpora === 'string' && args.corpora.trim() ? args.corpora.trim() : ''
      if (corpora) extra.push('--corpora', corpora)
      if (args?.full === true) extra.push('--full')
      const text = await runPreflight(config, query, extra, config.toolTimeoutMs, exec?.signal)
      if (!text.trim()) return `rag_search: no output for "${query}" (index missing or python failed).`
      return clamp(text, config.toolMaxChars)
    },
  }
}

export const name = 'dsh-preflight'
export const inject = ['agents']

export function apply(ctx, config) {
  const merged = { ...DEFAULTS, ...(config || {}) }

  let createUserMessage = null
  import('@deepseek-ai/dsh-llm')
    .then((mod) => { if (mod && typeof mod.createUserMessage === 'function') createUserMessage = mod.createUserMessage })
    .catch(() => {})

  // 1) rag_search tool — optional service, so the injection half still works
  //    in a profile without a tool registry.
  if (merged.tool !== false) {
    const definition = buildRagSearchTool(merged)
    const register = (toolCtx) => toolCtx.effect(() => {
      const tools = toolCtx.tools
      if (!tools || typeof tools.register !== 'function') return () => {}
      try {
        return tools.register(definition)
      } catch {
        return () => {}
      }
    })
    if (typeof ctx.inject === 'function') {
      try {
        ctx.inject(['tools'], register)
      } catch {
        register(ctx)
      }
    } else {
      register(ctx)
    }
  }

  // 2) pre-step injection
  if (merged.inject === false) return

  ctx.on('agent/created', ({ agent }) => {
    let seenKey = ''
    agent.ctx.effect(() => {
      const stop = agent.ctx.on('agent/pre-step', async ({ messages, signal }, next) => {
        let decision
        try {
          decision = await next()
        } catch {
          return next()
        }
        try {
          if (merged.enabled === false) return decision
          if (!decision || decision.kind !== 'enter' || !Array.isArray(decision.messages)) return decision
          const query = lastUserText(decision.messages)
          if (query.length < merged.minQueryChars) return decision
          if (merged.skipPrefixes.some((prefix) => query.startsWith(prefix))) return decision

          const key = `${decision.messages.length}:${query.slice(0, 200)}`
          if (key === seenKey) return decision
          seenKey = key

          const text = await runPreflight(merged, query, ['-k', String(merged.k)], merged.timeoutMs, signal)
          if (!text.trim()) return decision
          const injected = buildInjection(text, merged, createUserMessage)
          return { ...decision, messages: [...decision.messages, injected] }
        } catch {
          return decision
        }
      })
      return stop
    })
  })
}
