import { apiPost } from './client'
import type { SqlQueryRequest, SqlQueryResponse } from './types'

export function executeQuery(sql: string, params: unknown[] = [], writeMode = false): Promise<SqlQueryResponse> {
  const req: SqlQueryRequest = { sql, params, write_mode: writeMode }
  return apiPost<SqlQueryResponse>('/sql/query', req)
}
