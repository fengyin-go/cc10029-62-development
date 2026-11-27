/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

/** 目标页检索到的导师名额：语义上等同 mentor_roster 的一行。 */
export type MentorRow = EntryRow & {
  导师姓名: string
  指导方向: string
  学期: string
  可指导名额: number
  已占名额: number
  剩余名额: number
}

export type MentorSearchResult = {
  items: MentorRow[]
  total: number
  page: number
  size: number
  学期: string
  目标编号: string
  责任教师: string
}

/** 回看单张目标的候选资格。 */
export type PairingStatus = {
  目标编号: string
  目标id: number
  责任教师: string
  学期: string
  结对状态: string
  候选资格: string
  候选导师: string
  候选学期: string
  候选名额编号: number | null
  结对记录编号: number | null
  待办状态: string
  待办事项: string
  已具备确认资格: boolean
  需更换导师: boolean
  说明: string
}

export type PairingResult = {
  ok: boolean
  message: string
  pair: EntryRow | null
  goal?: Record<string, unknown> | null
  idempotent: boolean
}
