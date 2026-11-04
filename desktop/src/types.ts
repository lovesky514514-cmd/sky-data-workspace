export type Route = 'tasks' | 'results' | 'ai' | 'settings';
export type TaskAction = 'pause' | 'rerun' | 'resume' | 'copy' | 'cancel' | 'delete';
export interface Task {
  task_id: string;
  name: string;
  urls: string[];
  fields: string[];
  status: string;
  total: number;
  completed: number;
  failed: number;
  progress: number;
  record_count: number;
  created_at: string;
  updated_at: string;
  last_run_at: string | null;
  next_run_at: string | null;
  interval_seconds: number | null;
}
export interface TaskList {
  tasks: Task[];
  total: number;
  counts: Record<string, number>;
  records: number;
}
export interface RecordRow {
  record_id: string;
  task_id: string;
  source_url: string;
  retrieved_at: string;
  content_hash: string;
  evidence_locator: string;
  raw_reference: string;
  review_status: string;
  data: Record<string, unknown>;
}
export interface AIStatus {
  ai: {
    connected: boolean;
    enabled: boolean;
    installed: boolean | null;
    model: string;
    state: string;
    server_version?: string;
    details?: { parameter_size?: string; quantization_level?: string };
  };
  knowledge_available: boolean;
  inference_mode: string;
  cpu_count: number;
  preferences: { ai_enabled: boolean; cpu_threads: number; gpu_layers: number };
}
export interface Preview {
  kind: string;
  title: string;
  fields: string[];
  rows: { data: Record<string, unknown>; locator: string }[];
  total_rows: number;
  warnings: string[];
}
export interface Answer {
  answer: string;
  citations: string[];
  missing: boolean;
  sources: { id: string; title: string; excerpt: string }[];
  elapsed_seconds: number;
}
