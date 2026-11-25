// The landing page's document list must match the manifest (no drift, no invented documents).
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { FICTIONAL_SOPS, PUBLIC_GUIDANCE } from './corpus'

function activeManifestEntries() {
  const text = readFileSync(resolve(process.cwd(), '../corpus/manifest.yaml'), 'utf8') // vitest runs in frontend/
  return text.split(/\n(?=- doc_code:)/).filter((b) => b.startsWith('- doc_code:')).map((block) => {
    const field = (name) => block.match(new RegExp(`^\\s*-?\\s*${name}:\\s*"?([^"\\n]*)"?`, 'm'))?.[1].trim()
    return { code: field('doc_code'), title: field('title'), status: field('status') }
  }).filter((e) => e.status === 'active')
}

describe('landing page corpus', () => {
  it('lists exactly the active documents of corpus/manifest.yaml, with their titles', () => {
    const manifest = activeManifestEntries().map((e) => [e.code, e.title])
    expect([...PUBLIC_GUIDANCE, ...FICTIONAL_SOPS].sort()).toEqual(manifest.sort())
  })
  it('every internal SOP is a fictional ACME document', () => {
    expect(FICTIONAL_SOPS.every(([code]) => code.startsWith('ACME-'))).toBe(true)
    expect(PUBLIC_GUIDANCE.some(([code]) => code.startsWith('ACME-'))).toBe(false)
  })
})
