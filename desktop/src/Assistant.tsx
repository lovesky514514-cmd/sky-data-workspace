import { useState } from 'react';
import { Sparkles, ArrowUp, BookOpen, ShieldCheck, Search, Clock3 } from 'lucide-react';
import { api } from './bridge';
import { errorText } from './format';
import { Spinner } from './components';
import type { Answer, AIStatus } from './types';

export default function Assistant({ status }: { status: AIStatus | null }) {
  const [question, setQuestion] = useState(''),
    [messages, setMessages] = useState<{ question: string; answer?: Answer; error?: string }[]>([]);
  const [busy, setBusy] = useState(false),
    [seconds, setSeconds] = useState(0);
  const [tab, setTab] = useState<'ask' | 'knowledge'>('ask'),
    [knowledge, setKnowledge] = useState<{ id: string; title: string; excerpt: string }[]>([]);
  async function submit(value = question) {
    if (!value.trim() || busy) return;
    if (tab === 'knowledge') {
      setBusy(true);
      try {
        const r = await api<{ results: typeof knowledge }>('/api/knowledge/search', {
          query: value,
          limit: 3,
        });
        setKnowledge(r.results);
      } catch (e) {
        setMessages((m) => [...m, { question: value, error: errorText(e) }]);
      } finally {
        setBusy(false);
      }
      return;
    }
    setQuestion('');
    setBusy(true);
    setSeconds(0);
    const index = messages.length;
    setMessages([...messages, { question: value }]);
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    try {
      const answer = await api<Answer>('/api/ai/ask', { question: value });
      setMessages((m) => m.map((v, i) => (i === index ? { ...v, answer } : v)));
    } catch (e) {
      setMessages((m) => m.map((v, i) => (i === index ? { ...v, error: errorText(e) } : v)));
    } finally {
      clearInterval(timer);
      setBusy(false);
    }
  }
  return (
    <div className="assistant-layout">
      <section className="panel assistant-main">
        <div className="assistant-tabs">
          <button className={tab === 'ask' ? 'active' : ''} onClick={() => setTab('ask')}>
            <Sparkles size={15} />
            AI 问答
          </button>
          <button
            className={tab === 'knowledge' ? 'active' : ''}
            onClick={() => setTab('knowledge')}
          >
            <BookOpen size={15} />
            本地知识检索
          </button>
          <span className="local-badge">LOCAL ONLY</span>
        </div>
        <div className="conversation">
          {tab === 'ask' && !messages.length && (
            <div className="assistant-welcome">
              <div className="assistant-orb">
                <Sparkles size={28} />
              </div>
              <span className="eyebrow">YOUR DATA COPILOT</span>
              <h2>让采集规则更清楚</h2>
              <p>我会先查询本地知识库，再帮助你理解采集方法、字段口径与质量检查。</p>
              <div className="suggestions">
                {[
                  '静态网页和动态网页应该如何选择工具？',
                  '如何核验财务数据的金额与单位？',
                  '扫描版 PDF 的数字应该如何处理？',
                ].map((q) => (
                  <button key={q} onClick={() => submit(q)} disabled={busy}>
                    {q}
                    <ArrowUp size={14} />
                  </button>
                ))}
              </div>
            </div>
          )}
          {tab === 'ask' &&
            messages.map((message, i) => (
              <div className="message-pair" key={i}>
                <div className="user-message">{message.question}</div>
                {message.answer && (
                  <div className="ai-message">
                    <span className="ai-author">
                      <Sparkles size={14} />
                      SKY 助手
                    </span>
                    <p>{message.answer.answer}</p>
                    <div className="citations">
                      {message.answer.sources.map((s) => (
                        <details key={s.id}>
                          <summary>
                            <BookOpen size={12} />
                            {s.title}
                          </summary>
                          <p>{s.excerpt}</p>
                        </details>
                      ))}
                    </div>
                    <small>
                      知识库引用已对照 · {message.answer.elapsed_seconds.toFixed(1)} 秒
                      {message.answer.missing ? ' · 原始来源不足' : ''}
                    </small>
                  </div>
                )}
                {message.error && <div className="inline-error">{message.error}</div>}
                {busy && i === messages.length - 1 && (
                  <div className="thinking">
                    <Spinner />
                    <span>正在查询规则并生成回答…</span>
                    <small>{seconds}s</small>
                  </div>
                )}
              </div>
            ))}
          {tab === 'knowledge' && (
            <div className="knowledge-results">
              <div className="knowledge-intro">
                <BookOpen size={26} />
                <h3>直接检索本地研究规则</h3>
                <p>不调用模型；支持采集方式、证据、字段、单位等关键词。</p>
              </div>
              {knowledge.map((k) => (
                <article key={k.id}>
                  <h3>{k.title}</h3>
                  <p>{k.excerpt}</p>
                  <code>{k.id}</code>
                </article>
              ))}
            </div>
          )}
        </div>
        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <textarea
            aria-label="输入问题"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={1000}
            placeholder={
              tab === 'ask' ? '询问采集方法、字段定义或校验规则…' : '搜索本地知识关键词…'
            }
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void submit();
              }
            }}
          />
          <div>
            <span>{tab === 'ask' ? 'Qwen3.5 · 9B · 本地运行' : 'SQLite · 本地检索'}</span>
            <button aria-label="发送问题" disabled={busy || !question.trim()}>
              {busy ? <Spinner /> : tab === 'ask' ? <ArrowUp size={19} /> : <Search size={18} />}
            </button>
          </div>
        </form>
      </section>
      <aside className="assistant-aside">
        <div className="panel side-card">
          <div className="side-card-icon">
            <ShieldCheck size={21} />
          </div>
          <h3>事实来自来源</h3>
          <p>模型提供建议与映射。公司金额、日期等事实必须从真实网页或文件中获取，并保留证据。</p>
        </div>
        <div className="panel side-card">
          <BookOpen size={20} />
          <h3>带出处的回答</h3>
          <p>每次问答先调用本地知识检索。引用可以展开查看，研究规则仍需业务样本验证。</p>
        </div>
        <div className="side-note">
          <Clock3 size={16} />
          <p>
            当前为 {status?.inference_mode === 'cpu' ? 'CPU' : '自动GPU'} 模式。CPU 问答通常需要约
            75–90 秒，期间你可以继续管理任务。
          </p>
        </div>
      </aside>
    </div>
  );
}
