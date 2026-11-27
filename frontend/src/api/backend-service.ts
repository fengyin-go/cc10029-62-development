import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type {
  ActionResult,
  EntryRow,
  MentorSearchResult,
  OverviewResult,
  PageResult,
  PairingResult,
  PairingStatus,
} from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

/** 目标页按学期检索导师；direction 为空时返回该学期全部有名额的导师。 */
export async function searchMentors(
  goalId: number,
  direction = '',
): Promise<MentorSearchResult> {
  const query = new URLSearchParams({ direction }).toString()
  const response = await request(`/api/semester_goal/${goalId}/mentors?${query}`)
  if (!response.ok) throw new Error(await errorText(response, '导师检索失败'))
  return await response.json()
}

export async function loadPairingStatus(goalId: number): Promise<PairingStatus> {
  const response = await request(`/api/semester_goal/${goalId}/pairing`)
  if (!response.ok) throw new Error(await errorText(response, '候选资格读取失败'))
  return await response.json()
}

export async function initiatePairing(
  goalId: number,
  options: { rosterId?: number; mentor?: string; direction?: string },
): Promise<PairingResult> {
  const response = await request(`/api/semester_goal/${goalId}/pairing`, {
    method: 'POST',
    body: JSON.stringify({
      roster_id: options.rosterId ?? null,
      mentor: options.mentor ?? null,
      direction: options.direction ?? null,
    }),
  })
  if (!response.ok) throw new Error(await errorText(response, '发起结对失败'))
  return await response.json()
}

export async function acceptPairing(pairId: number): Promise<PairingResult> {
  const response = await request(`/api/mentor_pair/${pairId}/accept`, { method: 'POST' })
  if (!response.ok) throw new Error(await errorText(response, '受理结对失败'))
  return await response.json()
}

async function errorText(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.json()
    return String(payload?.detail ?? fallback)
  } catch {
    return fallback
  }
}
