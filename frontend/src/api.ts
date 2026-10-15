export type CouncilStatus = 'brief' | 'slices' | 'structure' | 'review' | 'ready'

export const LABELS = ['idea', 'question', 'proposal', 'constraint', 'risk'] as const
export type Label = (typeof LABELS)[number]
export type RunState = 'waiting' | 'running' | 'done' | 'failed'
export type StepName = 'slice' | 'slice_judge' | 'label' | 'label_judge' | 'structure' | 'structure_judge'
  | 'idea_discovery' | 'idea_judge' | 'repository_discovery' | 'repository_judge'
  | 'design_discovery' | 'design_judge' | 'project_decisions_discovery' | 'project_decisions_judge'
  | 'question_discovery' | 'question_judge'
  | 'proposal_discovery' | 'proposal_judge' | 'decision_analysis' | 'decision_judge'
  | 'outcome_discovery' | 'outcome_judge' | 'task_plan' | 'task_plan_judge'
  | 'notes_translation'
export interface ModelRun { model: string; state: RunState; error: string | null }
/** skipped — судья не понадобился: участники сошлись. */
export interface Step { name: StepName; state: RunState | 'skipped'; runs: ModelRun[] }
/** Что предложил участник; вариантов несколько, если он видит неоднозначность. */
export interface Vote { model: string; labels: Label[] }
export interface LabeledFragment {
  id: number; text: string
  /** Итоговый тип; council_label — что сказал совет, если человек выбрал другой. */
  label: Label; reason: string; council_label: Label
  /** agreed — участники сошлись, judge — разошлись и решил судья. */
  decided_by: 'agreed' | 'judge'; votes: Vote[]
  /** Пояснение судьи нарезки о границе этого фрагмента. */
  slice_note: string | null
}
/** Нарезка и разметка текста советом: идёт в фоне минутами, фронт опрашивает совет. */
export interface Slicing {
  state: 'running' | 'done' | 'failed'; steps: Step[]; fragments: LabeledFragment[]; error: string | null
  /** Свой у каждого запуска: правка типа несёт его, чтобы не лечь на фрагменты новой нарезки. */
  run: string
  /** Текст, который нарезали: исходник мог поменяться после запуска. */
  text: string
}
export interface Council {
  id: string; name: string; status: CouncilStatus; brief: string
  /** Каждый участник (хоть один) предлагает свой вариант, не видя чужих; судья выбирает лучший, а единственный проверяет. */
  participants: string[]; judge: string
  updated_at: string
  /** Проект совета (Project.id): его репозитории подставляются в потоках, его папка — каталог заметок. '' — без проекта. */
  project: string
  slicing: Slicing | null
  structure: Structure | null
  /** Потоки подтверждённых групп; null — группы ещё не подтверждены. */
  streams: Stream[] | null
  /** Исследование репозитория и макета на весь совет; null — к нему ещё не приступали. */
  research: Research | null
  /** План задач на весь совет, черновик его выгрузки в папку задач и последняя выгрузка. */
  tasks: TaskPlan | null; tasks_draft: TasksDraft | null; tasks_export: TasksExport | null
}

/**
 * Этап «Исследование» — на весь совет: необязательный скан репозитория и шаг «Репозиторий», потом так же шаг
 * «Дизайн». Одна карта кода и одно описание макета под идеи всех групп; поток берёт их себе копией, когда его
 * начинают.
 */
export interface Research {
  scan: RepositoryScan | null; repository: RepositoryStep | null
  design_scan: DesignScan | null; design: DesignStep | null
}

/** Фрагменты вокруг одной задумки. Общий фрагмент стоит в нескольких группах тем же номером. */
export interface Group {
  id: string; title: string; fragment_ids: number[]; idea_fragment_ids: number[]
  /** Идеи в тексте нет: её восстановит следующий этап. */
  missing_idea: boolean
  /** Какие из fragment_ids есть и в других группах. */
  shared_fragment_ids: number[]
}
/** depends_on — source требует результата target; related — связаны без зависимости. */
export interface GroupRelation { source: string; target: string; type: 'depends_on' | 'related'; reason: string }
export interface StructureDecision { issue: string; decision: string; reason: string }
/** Раскладка готовой нарезки по группам; slicing_run и labels — из какой нарезки и с какими типами. */
export interface Structure {
  state: 'running' | 'done' | 'failed'; run: string; slicing_run: string; labels: Record<number, Label>
  steps: Step[]; groups: Group[]; relations: GroupRelation[]; decisions: StructureDecision[]
  /** Как предложил совет; groups и relations — с правками человека, edited — они различаются. */
  proposal: { groups: Group[]; relations: GroupRelation[] } | null; edited: boolean
  /** Сколько раз группы правили: правка несёт версию, к которой сделана. */
  revision: number
  error: string | null
}
/** Формулировка идеи, как её восстановили по фрагментам группы; models — кто предложил. */
export interface IdeaOption { idea: string; evidence: number[]; reason: string; models: string[] }
/**
 * Что предлагает совет. idea null — не предлагает (никто не взялся или судья не принял ни
 * один вариант), reason — почему. option — какой из вариантов предложен как есть; null —
 * судья свёл формулировки.
 */
export interface IdeaProposal {
  idea: string | null; evidence: number[]; reason: string; decided_by: 'agreed' | 'judge'; option: number | null
}
/** Поиск идеи группы, в тексте которой её нет: идёт в фоне минутами, фронт опрашивает совет. */
export interface IdeaDiscovery {
  state: 'running' | 'done' | 'failed'; run: string; steps: Step[]
  options: IdeaOption[]; proposal: IdeaProposal | null; error: string | null
}
/** Где в репозитории подтверждение: файл, строки, символ. */
export interface Evidence { path: string; lines: string | null; symbol: string | null }
/** Факт о том, как система устроена сейчас: verified — подтверждён кодом, inferred — вывод, unknown — не установлен. */
export interface RepositoryFinding {
  id: string; statement: string; status: 'verified' | 'inferred' | 'unknown'; evidence: Evidence[]; relevance: string
}
/** Как поведение проходит через систему: откуда начинается и через что идёт. */
export interface RepositoryFlow {
  name: string; entry_point: string; entry_file: string; steps: { description: string; finding_ids: string[] }[]
}
export interface CoverageArea {
  area: string; status: 'covered' | 'partial' | 'not_investigated' | 'not_applicable'; evidence_ids: string[]; reason: string
}
export interface RepositoryUnknown { question: string; reason: string; investigate: string[] }
/** Задание на доисследование от судьи. */
export interface FollowUp { objective: string; reason: string; targets: string[]; related_finding_ids: string[] }
/** Проверенная карта существующей реализации — как система устроена сейчас, а не как её менять. */
export interface RepositoryMap {
  findings: RepositoryFinding[]; flows: RepositoryFlow[]; coverage: CoverageArea[]; unknowns: RepositoryUnknown[]
  documentation_conflicts: string[]
}
/** Сколько рабочих копий можно сканировать разом — как на сервере. */
export const REPOSITORIES_MAX = 10
/**
 * Рабочая копия скана: name — её папка в снимке (у нескольких пути карты начинаются с неё, у одной —
 * пусто), путь, как его ввёл человек, коммит (dirty — с незакоммиченными правками), сколько файлов,
 * сколько их вне sparse checkout и чего нет в снимке (нескачанные подмодули, ссылки — с причиной).
 */
export interface ScannedRepository {
  name: string; path: string; root: string; commit_sha: string; dirty: boolean
  files: number; outside: number; omitted: string[]; omitted_count: number
}
/**
 * Скан репозиториев под идею: какие рабочие копии и сколько проходов. complete — судья счёл исследование
 * достаточным; иначе в follow_up — что доисследовать не успели.
 */
export interface RepositoryScan {
  state: 'running' | 'done' | 'failed'; run: string; idea: string; repositories: ScannedRepository[]
  rounds: number; steps: Step[]; complete: boolean; result: RepositoryMap | null
  follow_up: FollowUp[]; error: string | null
}
/** Шаг «Репозиторий», как его прошёл человек: пропустил или утвердил карту скана scan_run. */
export interface RepositoryStep { by: 'skipped' | 'scan'; scan_run: string }
/** Сколько ссылок на макет можно дать разом — как на сервере. */
export const LINKS_MAX = 10
/** Узел макета Figma: страница, сам узел и его имя. */
export interface DesignNode { page_id: string; node_id: string; name: string }
/** Факт о макете: verified — видно в макете (evidence — узлы), inferred — вывод, unknown — не установлено. */
export interface DesignFinding {
  id: string; statement: string; status: 'verified' | 'inferred' | 'unknown'; evidence: DesignNode[]; relevance: string
}
export interface DesignAction {
  action: string; result: string | null; status: 'verified' | 'inferred' | 'unknown'; finding_ids: string[]
}
/** Экран макета: зачем он, какие данные, что на нём можно сделать и в каких состояниях он нарисован. */
export interface DesignScreen {
  name: string; node_id: string; purpose: string; data: string[]; actions: DesignAction[]
  states: { name: string; node_id: string }[]
}
export interface DesignFlow { name: string; steps: RepositoryFlow['steps']; status: 'verified' | 'inferred' | 'unknown' }
export interface DesignCoverage { area: string; status: CoverageArea['status']; reason: string }
export interface DesignUnknown { question: string; reason: string; investigate: DesignNode[] }
export interface DesignFollowUp { objective: string; reason: string; targets: DesignNode[]; related_finding_ids: string[] }
/** Проверенное описание макета: что предусмотрено в дизайне, а не как это реализовать. */
export interface DesignMap {
  findings: DesignFinding[]; screens: DesignScreen[]; flows: DesignFlow[]; coverage: DesignCoverage[]
  unknowns: DesignUnknown[]; design_conflicts: string[]
}
/** Какой макет читали: файл, его версия, узлы из ссылок, сколько страниц и картинок в снимке. */
export interface FigmaSource {
  file_key: string; name: string; version: string; last_modified: string; requested: DesignNode[]
  pages: number; images: number
}
/**
 * Скан макета Figma под идею: по каким ссылкам, что легло в снимок (source — пусто, пока его нет) и сколько
 * проходов. complete — судья счёл исследование достаточным; иначе в follow_up — что доисследовать не успели.
 */
export interface DesignScan {
  state: 'running' | 'done' | 'failed'; run: string; idea: string; links: string[]; source: FigmaSource | null
  rounds: number; steps: Step[]; complete: boolean; result: DesignMap | null
  follow_up: DesignFollowUp[]; error: string | null
}
/** Шаг «Дизайн», как его прошёл человек: пропустил или утвердил описание скана scan_run. */
export interface DesignStep { by: 'skipped' | 'scan'; scan_run: string }
/** Идея потока, утверждённая человеком: записана в тексте, вариант совета как есть или своя. */
export interface StreamIdea { text: string; by: 'text' | 'council' | 'human'; evidence: number[] }
/**
 * Открытый вопрос: что ещё неизвестно. user — из текста, дословно; inferred — незаписанный,
 * на него отвечают предложения группы; discovered — недостающий; added — добавлен при отборе.
 */
export interface OpenQuestion {
  id: string; text: string; source: 'user' | 'inferred' | 'discovered' | 'added'
  source_question_id: number | null; proposal_ids: number[]; reason: string | null
  /** Для заметки: у вопроса из текста — та же неопределённость атомарно, одним предложением. */
  note: string | null
  /** Принятое решение проекта, которое вопрос пересматривает (ADR-0007). */
  revisits: string | null
  /**
   * «Технические детали»: вопрос об устройстве системы внутри, а не о её поведении — человек
   * решает, оставлять ли его. Нет у вопросов, найденных раньше.
   */
  technical?: boolean
}
/** След решения в коде: коммит с номером задачи, реализовавшей итог решения, в файле карты. */
export interface CodeTrail { issue: string; outcome: string; commit: string; file: string }
/**
 * Принятое решение проекта из каталога заметок: к какой идее, на какой вопрос, что решено, действует ли
 * оно и его след в коде; отобранное — насколько и почему относится к идее потока.
 */
export interface ProjectDecision {
  adr_id: string; idea: string; question: string; decision: string
  status: 'active' | 'under_review' | 'superseded'; superseded_by: string | null; found_in_code: CodeTrail[]
  relevance: 'applicable' | 'potential_conflict' | 'uncertain' | null; reason: string
}
/** Отбор прошлых решений проекта для потока: сколько их в каталоге, у скольких есть след и что отобрал совет. */
export interface DecisionsSearch {
  state: 'running' | 'done' | 'failed'; run: string; idea: string; repository: string; design: string
  catalog: number; traced: number; fingerprint: string; steps: Step[]; decisions: ProjectDecision[]; error: string | null
}
/** Поиск вопросов к утверждённой идее (idea — к какой; repository и design — с какой картой и описанием макета). */
export interface QuestionDiscovery {
  state: 'running' | 'done' | 'failed'; run: string; idea: string; repository: string; design: string
  decisions: string[]; decisions_seen: string
  /** Каталог заметок, с которым искали ('' — его не было): в другом есть неотобранные решения — отбор заново. */
  notes: string
  steps: Step[]; questions: OpenQuestion[]; error: string | null
}
/**
 * Новый вариант ответа на вопрос, найденный советом (P1, P2… сквозь поток). Варианты из текста —
 * фрагменты группы в OpenQuestion.proposal_ids. Ссылки — на ограничения и риски группы и на
 * другие вопросы, от которых он зависит; recommended — судья счёл его предпочтительным.
 */
export interface Proposal {
  id: string; text: string; reason: string; constraint_ids: number[]; risk_ids: number[]
  depends_on: string[]; recommended: boolean
}
/** Что совет нашёл к вопросу: recommended — один предпочтительный, alternatives — равноправные, none — ничего нового. */
export interface QuestionOptions {
  question_id: string; proposals: Proposal[]; verdict: 'recommended' | 'alternatives' | 'none'; reason: string | null
}
/** Поиск вариантов к отобранным вопросам: по вопросу за раз, готовые — в options по мере поиска. */
export interface ProposalDiscovery {
  state: 'running' | 'done' | 'failed'; run: string; scope: string[]; steps: Step[]
  options: QuestionOptions[]; error: string | null
}
/**
 * Выбор по вопросу: Fn — вариант из текста, Pn — найденный советом или свой, null — пока не решает
 * (unresolved). text — свой вариант человека: на сервер — с proposal null, с сервера — с его номером Pn.
 */
export interface Choice { question_id: string; proposal: string | null; text?: string | null }
/**
 * Что совет сказал по вопросу перед решением. validated — выбор человека проверен, проблем нет;
 * conflict — с ним проблема (решать всё равно человеку); recommended — для unresolved совет
 * предлагает вариант из тех, что есть; none — обоснованно выбрать нельзя. proposal — проверенный
 * или рекомендованный вариант; rationale — обоснование совета: в ADR — если человек его оставит.
 */
export interface QuestionAnalysis {
  question_id: string; verdict: 'validated' | 'conflict' | 'recommended' | 'none'; proposal: string | null
  constraint_conflicts: number[]; risk_ids: number[]; depends_on: string[]
  /** Выбор по вопросам из depends_on, каким он был при проверке («Q2: P5»): поменялся — проверяют заново. */
  context: string[]
  reason: string | null; rationale: string | null
  /** У conflict: что поправить — по шагу на правку. */
  fixes: DecisionFix[]
}
/** Что поправить, чтобы проблема с выбором ушла: в каком вопросе, что поменять и с чем это расходится. */
export interface DecisionFix { question_id: string; change: string; why: string }
/** Проверка выбора: по вопросу за раз, готовые — в analyses по мере проверки; choices — к какому выбору. */
export interface DecisionAnalysis {
  state: 'running' | 'done' | 'failed'; run: string; choices: string[]; steps: Step[]
  analyses: QuestionAnalysis[]; error: string | null
}
/**
 * Решение человека по вопросу — ADR: вариант и почему он; proposal null — вопрос оставлен открытым.
 * rationale_by: ai — обоснование совета, подтверждённое как есть; human — своё или поправленное.
 */
/**
 * Что сделано по вопросу отбора: выбор, проверка этого выбора и решение по нему. Вопрос тот же (key — номер и
 * формулировка) и выбор тот же — всё это подставляется снова, а не делается заново.
 */
export interface QuestionWork { key: string; choice: Choice; analysis: QuestionAnalysis | null; decision: Decision | null }

/** Вопрос, как его узнают после правки отбора: номер и формулировка. */
export const questionKey = (question: { id: string; text: string }) => `${question.id}: ${question.text}`

/** Выбор по вопросу, как его сравнивает сервер: вариант, а у своего — и текст. */
export const sameChoice = (a: Choice, b: Choice) =>
  a.question_id === b.question_id && a.proposal === b.proposal && (a.text ?? null) === (b.text ?? null)

/** Прежняя работа по вопросу отбора — если он тот же. */
export const earlierOf = (stream: Stream, question: { id: string; text: string }): QuestionWork | undefined =>
  stream.earlier.find(work => work.key === questionKey(question))

export interface Decision {
  question_id: string; proposal: string | null; rationale: string | null; rationale_by: 'ai' | 'human' | null
}
/** Решение, как его фиксирует человек: у открытого вопроса proposal и rationale — null. */
export interface DecisionDraft { question_id: string; proposal: string | null; rationale: string | null }
/** Неопределённость, которой нет среди вопросов потока: материал для нового поиска вопросов. */
export interface OutcomeGap { question: string; reason: string }
/**
 * Итог — наблюдаемое состояние системы после принятых решений (O1, O2…). adr_ids — какие
 * решения он реализует (ADR-n — решение по n-му вопросу отбора; каждое реализует ровно один
 * итог), adr_notes — что из каждого следует в его поведении; relies_on_adr_ids — решения других
 * итогов, на которые он опирается; project_decision_ids — на какие прошлые решения проекта
 * опирается; blocked_by — открытые вопросы, без решения которых его поведение не определить:
 * недостающее не додумывается.
 */
export interface Outcome {
  id: string; title: string; behavior: string; adr_ids: string[]; constraint_ids: number[]; risk_ids: number[]
  acceptance_criteria: string[]; blocked_by: string[]; gaps: OutcomeGap[]
  /** Нет у итогов, собранных раньше. */
  project_decision_ids?: string[]; adr_notes?: Record<string, string>; relies_on_adr_ids?: string[]
}
/** Сборка итогов из решений (decisions — к каким); uncovered_adr_ids — решения, не вошедшие ни в один итог. */
/** Новое решение задевает закреплённый итог: оставить его как есть или пересобрать — решает человек. */
export interface OutcomeTouch { outcome_id: string; adr_ids: string[]; reason: string }
export interface OutcomeDiscovery {
  state: 'running' | 'done' | 'failed'; run: string; decisions: string[]; steps: Step[]
  outcomes: Outcome[]; uncovered_adr_ids: string[]; error: string | null
  /** Закреплённые итоги: были готовы, их решения те же — их не пересобирали. */
  kept: string[]
  /** Какие закреплённые итоги задевают новые решения — ждут решения человека. */
  touched: OutcomeTouch[]
  /** Человек утвердил эти итоги: поток выгружают в заметки к ним. */
  approved: boolean
}
/**
 * Задача для coding agent (I1, I2…) из плана совета — часть ровно одного утверждённого итога (outcome_id — номер его
 * заметки, OUT-…): кому и зачем (user_story), где менять и что меняем, что именно сделать и где остановиться (scope).
 * adr_ids — решения номерами заметок; depends_on — задачи плана, результат которых ей нужен; open_questions — что
 * неясно в реализации: вопросы человеку и агенту, без ответа.
 */
export interface Issue {
  id: string; title: string; user_story: string; main_entry_points: string[]; current_state: string
  scope: string[]; outcome_id: string; adr_ids: string[]; constraint_ids: number[]; risk_ids: number[]
  depends_on: string[]; open_questions: string[]
}
/**
 * План задач на весь совет. basis — к чему спланировали: у каждого потока «сборка итогов:выгрузка»; поток с тех пор
 * поменяли — план устарел (это видно, сбрасывает человек). code — читали ли модели код, sources — каких рабочих
 * копий; uncovered — итоги, не вошедшие ни в одну задачу; skipped — что в план не вошло и почему.
 */
export interface TaskPlan {
  state: 'running' | 'done' | 'failed'; run: string; basis: Record<string, string>
  code: boolean; sources: ScannedRepository[]; steps: Step[]; issues: Issue[]
  uncovered: string[]; skipped: string[]; error: string | null
}
/** Номер задачи на весь проект (ISS-0012): его пишут в финальный коммит. */
export interface IssueNumber { key: string; id: string; issue_id: string; title: string; outcome_ids: string[] }
/** Черновик выгрузки плана в папку задач (root) — к плану plan; язык другой — переводит судья. */
export interface TasksDraft {
  state: 'running' | 'done' | 'failed'; run: string; plan: string; language: string; root: string
  steps: Step[]; notes: NotePlan[]; vanished: VanishedNote[]; numbers: IssueNumber[]; error: string | null
}
/** Последняя выгрузка плана: из какого черновика, к какому плану и в какую папку. */
export interface TasksExport {
  run: string; plan: string; language: string; root: string; notes: ExportedNote[]; numbers: IssueNumber[]
}
/**
 * Поток — подтверждённая группа под той же буквой. discovery — поиск её идеи, если её нет в
 * тексте; scan — необязательный скан репозитория под идею, repository — как прошли этот шаг
 * (карта идёт во все следующие); questions — поиск вопросов к утверждённой идее; scope — какие из них решать;
 * proposals — поиск вариантов к ним; choices — выбор по каждому; analysis — его проверка;
 * decisions — решения, которые зафиксировал человек; outcomes — итоги, собранные из них.
 */
export interface Stream {
  group: string; discovery: IdeaDiscovery | null; idea: StreamIdea | null
  scan: RepositoryScan | null; repository: RepositoryStep | null
  design_scan: DesignScan | null; design: DesignStep | null
  decisions_search: DecisionsSearch | null; project_decisions: ProjectDecision[] | null
  questions: QuestionDiscovery | null; scope: OpenQuestion[] | null
  proposals: ProposalDiscovery | null; choices: Choice[] | null
  analysis: DecisionAnalysis | null; decisions: Decision[] | null
  /** Работа по вопросам до последней правки отбора или выбора: по тем же вопросам и выбору она переносится. */
  earlier: QuestionWork[]
  /** Последние собранные итоги, пока правка выше их сняла: из них закрепляют готовое. */
  earlier_outcomes: OutcomeDiscovery | null
  outcomes: OutcomeDiscovery | null
  notes_draft: NotesDraft | null; notes: NotesExport | null
  /**
   * Сохранённое, пока поток до него не дошёл (считает сервер): прежние итоги, которые закрепятся, если решения
   * не поменяются. Дошёл — шаг показывает свой прогон, а в нём они с начала.
   */
  saved_outcomes: Outcome[]
}
/** issue — не заметка графа, а файл задачи для coding agent в папке задач проекта. */
export type NoteType = 'idea' | 'open_question' | 'proposal' | 'adr' | 'outcome' | 'issue'
/**
 * Заметка черновика выгрузки: какая часть потока (key), под каким номером, что предлагается записать
 * (text) и что с ней будет — новая, перепишется, уже такая, правили руками (совет не трогает).
 */
export interface NotePlan {
  key: string; id: string; type: NoteType; text: string; generated: string; links: string[]
  action: 'create' | 'update' | 'same' | 'edited'; current: string | null
}
/** Заметка прошлой выгрузки, которой в потоке больше нет: удалить можно, только если вне потока на неё не ссылаются. */
export interface VanishedNote { id: string; type: NoteType; text: string; linked_from: string[] }
/** Черновик выгрузки потока в заметки — к утверждённым итогам (outcomes); язык другой — переводит судья. */
export interface NotesDraft {
  state: 'running' | 'done' | 'failed'; run: string; outcomes: string; language: string; steps: Step[]
  /** Каталог заметок, для которого черновик собран: в другой его не записать. */
  root: string
  notes: NotePlan[]; vanished: VanishedNote[]; skipped: string[]; error: string | null
}
export interface ExportedNote {
  key: string; id: string; type: NoteType; generated: string; written: string; links: string[]; digest: string
  /** Исчезла из потока, а её оставили в каталоге: всё ещё потока, но в выгрузку не входит. */
  kept: boolean
}
/** Последняя выгрузка потока: из какого черновика и к каким утверждённым итогам. */
export interface NotesExport {
  run: string; outcomes: string; language: string; root: string; notes: ExportedNote[]
  /** Имена совета (O1, ADR-2) — номерами заметок этой выгрузки (OUT-…, ADR-…): так их называет план задач. */
  refs: Record<string, string>
}

/** Правка с экрана: меняются только присланные поля. */
export type CouncilPatch = Partial<Pick<Council, 'name' | 'brief' | 'participants' | 'judge' | 'project'>> & {
  /** Типы фрагментов готовой нарезки, {id: тип}: только изменённые, остальные не трогаются. */
  labels?: Record<number, Label>
  /** К какой нарезке относятся labels: Slicing.run. */
  slicing_run?: string
}

/** available — есть подключение к CLI: без него модель видна, но не запускается. */
export interface Model { alias: string; short_name: string; display_name: string; cli: string; available: boolean }
export interface Settings {
  models: Model[]; min_participants: number; default_participants: string[]; default_judge: string
  /** Каталог репозиториев для скана (COUNCIL_REPOS): пути — от него; null — путь абсолютный. */
  repositories: string | null
  /** Задан ли токен Figma (FIGMA_TOKEN): без него макет не сканировать. */
  figma: boolean
  /** Проекты: совет на экране берёт свой — его репозитории и папку документации. */
  projects: Project[]
}

/**
 * Проект: рабочие копии, папка документации и папка задач, которые совет берёт по нему, а не вводит в каждом
 * потоке. Пути — от каталога репозиториев (COUNCIL_REPOS) или, без него, абсолютные. notes_root и issues_root —
 * папки документации и задач, как их находит сервер (по этим путям выгрузка помнит, куда записала); null — папки
 * нет или она больше не годится, и тогда problem — почему.
 */
export interface Project {
  id: string; name: string; repositories: string[]; notes: string; issues: string; updated_at: string
  /** Версия: правка несёт ту, что правили; проект с тех пор поправили — 409. */
  revision: number
  notes_root: string | null; issues_root: string | null; problem: string | null
}
/** Проект, как его сохраняют: название, рабочие копии, папки документации и задач ('' — нет). */
export type ProjectDraft = Pick<Project, 'name' | 'repositories' | 'notes' | 'issues'>
/** Рабочие копии git в каталоге репозиториев — из них отмечают репозитории проекта. root null — каталог не задан. */
export interface WorkingCopies { root: string | null; paths: string[] }

/** Проект совета; нет его (без проекта или удалён) — null. */
export const projectOf = (council: Council, settings: Settings): Project | null =>
  (council.project && settings.projects.find(p => p.id === council.project)) || null

/** Каталог заметок совета — папка документации его проекта, как её находит сервер; null — потоки не выгрузить. */
export const notesOf = (council: Council, settings: Settings): string | null =>
  projectOf(council, settings)?.notes_root ?? null

/** Папка задач совета — его проекта, как её находит сервер; null — план задач не выгрузить. */
export const issuesOf = (council: Council, settings: Settings): string | null =>
  projectOf(council, settings)?.issues_root ?? null

/** Куда выгружают совет: потоки — в каталог заметок, план задач — в папку задач его проекта. */
export interface Folders { notes: string | null; issues: string | null }

export const foldersOf = (council: Council, settings: Settings): Folders =>
  ({ notes: notesOf(council, settings), issues: issuesOf(council, settings) })

/** Ответ сервера не 2xx. Сетевые сбои бросают обычный TypeError от fetch. */
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export const isNotFound = (e: unknown) => e instanceof ApiError && e.status === 404

/** Текст ошибки: `detail` из ответа FastAPI, иначе statusText (в HTTP/2 он часто пустой), иначе код. */
const errorMessage = async (res: Response) => {
  try {
    const { detail } = await res.json()
    if (typeof detail === 'string' && detail) return detail
  } catch { /* тело не JSON */ }
  return res.statusText || `HTTP ${res.status}`
}

const request = async <T,>(url: string, init?: RequestInit): Promise<T> => {
  const res = await fetch(url, init)
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res))
  return res.json()
}

const councilUrl = (id: string) => `/api/councils/${encodeURIComponent(id)}`
const projectUrl = (id: string) => `/api/projects/${encodeURIComponent(id)}`
const sendProject = (draft: ProjectDraft & { revision?: number }): RequestInit => ({
  headers: { 'content-type': 'application/json' }, body: JSON.stringify(draft),
})

/** К какой раскладке и версии её групп правка: Structure.run и revision. Не та — 409. */
export interface GroupsVersion { run: string; revision: number }

const editGroups = (id: string, action: 'merge' | 'split' | 'rename' | 'restore' | 'confirm',
                    at: GroupsVersion, body: object = {}) =>
  request<Council>(`${councilUrl(id)}/structure/${action}`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ run: at.run, revision: at.revision, ...body }),
  })

export const api = {
  councils: () => request<Council[]>('/api/councils'),
  council: (id: string) => request<Council>(councilUrl(id)),
  createCouncil: () => request<{ id: string }>('/api/councils', { method: 'POST' }),
  updateCouncil: (id: string, patch: CouncilPatch) => request<Council>(councilUrl(id), {
    method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(patch),
  }),
  startSlicing: (id: string) => request<Council>(`${councilUrl(id)}/slicing`, { method: 'POST' }),
  startStructure: (id: string) => request<Council>(`${councilUrl(id)}/structure`, { method: 'POST' }),
  /** group — где нажали: её буква и название остаются. */
  mergeGroups: (id: string, at: GroupsVersion, group: string, other: string) =>
    editGroups(id, 'merge', at, { group, other }),
  splitGroup: (id: string, at: GroupsVersion, group: string, fragmentIds: number[], title: string) =>
    editGroups(id, 'split', at, { group, fragment_ids: fragmentIds, title }),
  renameGroup: (id: string, at: GroupsVersion, group: string, title: string) =>
    editGroups(id, 'rename', at, { group, title }),
  restoreGroups: (id: string, at: GroupsVersion) => editGroups(id, 'restore', at),
  /** Группы на экране становятся потоками; у групп без идеи совет сразу её ищет. */
  confirmGroups: (id: string, at: GroupsVersion) => editGroups(id, 'confirm', at),
  /** Искать идею потока заново: после сбоя или без подключения к моделям. */
  seekIdea: (id: string, group: string) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/discovery`, { method: 'POST' }),
  /** Сканировать репозитории под идеи всех групп: пути — от каталога репозиториев или абсолютные. */
  scanRepository: (id: string, at: GroupsVersion, paths: string[]) =>
    request<Council>(`${councilUrl(id)}/research/repository/scan`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, paths }),
    }),
  /** Пройти шаг «Репозиторий» исследования: scanRun — утвердить карту этого скана, null — пропустить. */
  approveRepository: (id: string, at: GroupsVersion, scanRun: string | null) =>
    request<Council>(`${councilUrl(id)}/research/repository`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, scan_run: scanRun }),
    }),
  /** Сканировать макет Figma под идеи всех групп: ссылки на страницы или фреймы одного файла. */
  scanDesign: (id: string, at: GroupsVersion, links: string[]) =>
    request<Council>(`${councilUrl(id)}/research/design/scan`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, links }),
    }),
  /** Пройти шаг «Дизайн» исследования: scanRun — утвердить описание этого скана, null — пропустить. */
  approveDesign: (id: string, at: GroupsVersion, scanRun: string | null) =>
    request<Council>(`${councilUrl(id)}/research/design`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, scan_run: scanRun }),
    }),
  /** Сбросить исследование: сканы и пройденные шаги снимаются, начатые потоки работают со своей копией. */
  resetResearch: (id: string, at: GroupsVersion) =>
    request<Council>(`${councilUrl(id)}/research/reset`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision }),
    }),
  /** Начать поток: он берёт себе исследование совета, и совет сразу отбирает решения проекта или ищет вопросы. */
  startStream: (id: string, at: GroupsVersion, group: string, idea: string) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/start`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, idea }),
    }),
  /** Отметить прошлые решения проекта, которые учитывать в потоке (пусто — ни одного). Совет сразу ищет вопросы. */
  selectDecisions: (id: string, at: GroupsVersion, group: string, searchRun: string, keep: string[], idea: string) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/project-decisions`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, search_run: searchRun, keep, idea }),
    }),
  /** Отобрать решения проекта заново: после сбоя или без подключения к моделям. */
  searchDecisions: (id: string, group: string) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/project-decisions/search`, { method: 'POST' }),
  /** Собрать черновик выгрузки потока в заметки. */
  draftNotes: (id: string, at: GroupsVersion, group: string) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/notes/draft`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision }),
    }),
  /** Записать черновик draft: правки текста по ключу заметки и какие исчезнувшие заметки удалить. */
  writeNotes: (id: string, at: GroupsVersion, group: string, draft: string, edits: Record<string, string>, remove: string[]) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/notes`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, draft, edits, delete: remove }),
    }),
  /** Искать вопросы к идее потока заново: после сбоя или без подключения к моделям. */
  seekQuestions: (id: string, group: string) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/questions/discovery`, { method: 'POST' }),
  /**
   * Какие вопросы потоку решать: оставленные из найденных (их id) и свои (тексты). questionsRun —
   * к какому поиску отбор: каждый нумерует вопросы с Q1, и отбор к прежнему сервер отклонит (409).
   */
  approveScope: (id: string, at: GroupsVersion, group: string, questionsRun: string, keep: string[], added: string[]) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/questions`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, questions_run: questionsRun, keep, added }),
    }),
  /** Искать варианты к отобранным вопросам заново: после сбоя или без подключения к моделям. */
  seekProposals: (id: string, group: string) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/proposals/discovery`, { method: 'POST' }),
  /**
   * Выбор по каждому отобранному вопросу; совет сразу его проверяет. proposalsRun — к какому
   * поиску: у каждого свои номера Pn.
   */
  approveChoices: (id: string, at: GroupsVersion, group: string, proposalsRun: string, choices: Choice[]) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/choices`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, proposals_run: proposalsRun, choices }),
    }),
  /** Проверить выбор заново: после сбоя или без подключения к моделям. */
  checkChoices: (id: string, group: string) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/analysis`, { method: 'POST' }),
  /** Перепроверить выбор по одному вопросу: проверка остальных переносится. До того, как решения зафиксированы. */
  recheckChoice: (id: string, group: string, question: string) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/analysis/${encodeURIComponent(question)}`,
                     { method: 'POST' }),
  /** Решения по каждому отобранному вопросу; совет сразу собирает из них итоги. analysisRun — к какой проверке выбора. */
  approveDecisions: (id: string, at: GroupsVersion, group: string, analysisRun: string, decisions: DecisionDraft[]) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/decisions`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, analysis_run: analysisRun, decisions }),
    }),
  /** Собрать итоги заново: после сбоя или без подключения к моделям. */
  seekOutcomes: (id: string, group: string) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/outcomes/discovery`, { method: 'POST' }),
  /** Утвердить итоги — те, что на экране (outcomesRun): дальше поток выгружают в заметки. */
  approveOutcomes: (id: string, at: GroupsVersion, group: string, outcomesRun: string) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/outcomes`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, outcomes_run: outcomesRun }),
    }),
  /** Закреплённый итог, который задевают новые решения: rebuild — пересобрать итоги без него среди закреплённых, иначе — оставить. */
  settleTouch: (id: string, at: GroupsVersion, group: string, outcomesRun: string, outcomeId: string, rebuild: boolean) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/outcomes/touched`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, outcomes_run: outcomesRun, outcome_id: outcomeId, rebuild }),
    }),
  /** Построить план задач на весь совет: потоки утверждены и выгружены. После сбоя — заново. */
  planTasks: (id: string, at: GroupsVersion) =>
    request<Council>(`${councilUrl(id)}/tasks`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision }),
    }),
  /** Сбросить план и черновик его выгрузки: выгрузка остаётся — по ней новая найдёт свои файлы и номера. */
  resetTasks: (id: string, at: GroupsVersion) =>
    request<Council>(`${councilUrl(id)}/tasks/reset`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision }),
    }),
  /** Собрать черновик выгрузки плана в папку задач. */
  draftTasks: (id: string, at: GroupsVersion) =>
    request<Council>(`${councilUrl(id)}/tasks/draft`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision }),
    }),
  /** Записать черновик draft в папку задач: правки текста по ключу файла и какие исчезнувшие файлы удалить. */
  writeTasks: (id: string, at: GroupsVersion, draft: string, edits: Record<string, string>, remove: string[]) =>
    request<Council>(`${councilUrl(id)}/tasks/write`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, draft, edits, delete: remove }),
    }),
  /** text null — идея записана в тексте группы, её не правят. */
  approveIdea: (id: string, at: GroupsVersion, group: string, text: string | null) =>
    request<Council>(`${councilUrl(id)}/streams/${encodeURIComponent(group)}/idea`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ run: at.run, revision: at.revision, ...(text === null ? {} : { text }) }),
    }),
  settings: () => request<Settings>('/api/settings'),
  projects: () => request<Project[]>('/api/projects'),
  createProject: (draft: ProjectDraft) => request<Project>('/api/projects', { method: 'POST', ...sendProject(draft) }),
  /** revision — версия проекта, которую правили: его с тех пор поправили (другая вкладка) — 409. */
  updateProject: (id: string, draft: ProjectDraft, revision: number) =>
    request<Project>(projectUrl(id), { method: 'PUT', ...sendProject({ ...draft, revision }) }),
  /** Удалить проект: выбран у советов — 409, сначала выбрать им другой. */
  deleteProject: async (id: string) => {
    const res = await fetch(projectUrl(id), { method: 'DELETE' })
    if (!res.ok) throw new ApiError(res.status, await errorMessage(res))
  },
  /** Рабочие копии в каталоге репозиториев: из них отмечают репозитории проекта. */
  workingCopies: () => request<WorkingCopies>('/api/repositories'),
}

/**
 * Запустить ход совета (нарезку, группы, поиск идеи или вопросов). Если его уже запустили
 * (409: вторая вкладка, повторный клик, потерянный ответ на прошлый запуск) — вернуть совет с
 * ним, чтобы экран за ним следил: он идёт или на месте уже не тот ход, что был на экране, —
 * пусть даже успел закончиться, — или хода на месте нет вовсе (сервер снял отметку решений
 * проекта и всё ниже: каталог поменялся). run — где этот ход в совете, onScreen — совет на экране.
 * 409 бывает и не про это: группы устарели, идея уже утверждена, — тогда ход на месте прежний
 * и не идёт, и это отказ словами сервера, как и временный (503, 423).
 */
export const startOrFollow = async (start: () => Promise<Council>, onScreen: Council,
                                    run: (council: Council) => { state: string; run: string } | null | undefined,
): Promise<Council> => {
  const shown = run(onScreen)?.run
  try {
    return await start()
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      const council = await api.council(onScreen.id)
      const now = run(council)
      if (now ? now.state === 'running' || now.run !== shown : shown !== undefined) return council
    }
    throw e
  }
}

/** Поток группы в совете: где искать его ходы. */
export const streamOf = (council: Council, group: string) => council.streams?.find(s => s.group === group)

/**
 * Группы разложены по другим типам, чем сейчас у фрагментов: человек поправил тип после
 * раскладки. Группы могли устареть — стоит разложить заново.
 */
export const structureIsStale = (council: Council): boolean => {
  const { structure, slicing } = council
  if (!structure || structure.state !== 'done' || !slicing) return false
  if (structure.slicing_run !== slicing.run) return true
  return slicing.fragments.some(f => structure.labels[f.id] !== f.label)
}

/**
 * Группы подтверждены: каждая стала потоком. Новый состав групп или новая раскладка
 * подтверждение снимают, переименование — нет.
 */
export const groupsConfirmed = (council: Council): boolean =>
  council.streams !== null && council.structure?.state === 'done'

/**
 * Ходы потока по цепочке, как STREAM_RUNS на сервере: поиск идеи, сканы репозитория и макета, отбор решений
 * проекта, поиск вопросов и вариантов, проверка выбора, сборка итогов и перевод заметок.
 */
const STREAM_RUNS = ['discovery', 'scan', 'design_scan', 'decisions_search', 'questions', 'proposals', 'analysis',
  'outcomes', 'notes_draft'] as const

/** Ходы потока: какой идёт — страница опрашивает сервер. */
export const searchesOf = (stream: Stream) => STREAM_RUNS.map(field => stream[field])

/** Совет работает над звеном from или ниже: менять его сервер не даст (423), кнопки — тоже. */
export const runningFrom = (stream: Stream, from: (typeof STREAM_RUNS)[number]): boolean =>
  STREAM_RUNS.slice(STREAM_RUNS.indexOf(from)).some(field => stream[field]?.state === 'running')

/** Совет исследует код или макет: страница опрашивает сервер. */
export const researching = (council: Council): boolean =>
  council.research?.scan?.state === 'running' || council.research?.design_scan?.state === 'running'

/** Совет строит план задач или переводит его выгрузку: страница опрашивает сервер. */
export const planning = (council: Council): boolean =>
  council.tasks?.state === 'running' || council.tasks_draft?.state === 'running'

/** Совет работает хоть над одним потоком — ищет, проверяет или собирает, — исследует код и макет или планирует. */
export const seeking = (council: Council): boolean => researching(council) || planning(council)
  || (council.streams?.some(stream => searchesOf(stream).some(run => run?.state === 'running')) ?? false)

/** Идеи всех групп одним текстом — как их помнит скан исследования: поменяли — исследование было к прежним. */
export const ideasOf = (council: Council): string | null => {
  const streams = council.streams
  if (!streams || streams.some(stream => !stream.idea)) return null
  const titles = new Map((council.structure?.groups ?? []).map(g => [g.id, g.title]))
  return streams.map(stream => `${stream.group}. ${titles.get(stream.group) ?? ''}: ${stream.idea?.text}`).join('\n')
}

/** Исследование пройдено: оба шага — сканом или пропуском. Потоки можно начинать. */
export const researched = (council: Council): boolean => !!council.research?.repository && !!council.research.design

/** Поток начат с тем исследованием, что в совете сейчас: иначе его можно начать заново. */
export const startedWithResearch = (council: Council, stream: Stream): boolean => {
  const research = council.research
  return !!stream.repository && !!stream.design && !!research?.repository && !!research.design
    && stream.repository.by === research.repository.by && stream.repository.scan_run === research.repository.scan_run
    && stream.design.by === research.design.by && stream.design.scan_run === research.design.scan_run
}

/** Итог готов к разработке: его не держит ни открытый вопрос, ни пробел, и есть чем проверить, что он готов. */
export const outcomeReady = (outcome: Outcome): boolean =>
  outcome.blocked_by.length === 0 && outcome.gaps.length === 0 && outcome.acceptance_criteria.length > 0

/** Итоги потока можно утвердить: ни один не держит открытый вопрос или пробел — как проверяет сервер. */
export const outcomesFree = (outcomes: Outcome[]): boolean =>
  outcomes.every(outcome => outcome.blocked_by.length === 0 && outcome.gaps.length === 0)

/** К чему был бы план сейчас — как basis_of на сервере: у каждого потока «сборка итогов:выгрузка». */
export const tasksBasis = (council: Council): Record<string, string> => Object.fromEntries((council.streams ?? []).map(
  stream => [stream.group, `${stream.outcomes?.run ?? ''}:${stream.notes?.run ?? ''}`]))

/** План к другим итогам или выгрузкам, чем сейчас: поток поменяли после него — сбросить и спланировать заново. */
export const tasksStale = (council: Council): boolean => {
  const plan = council.tasks
  if (!plan) return false
  const now = tasksBasis(council)
  const groups = new Set([...Object.keys(now), ...Object.keys(plan.basis)])
  return [...groups].some(group => now[group] !== plan.basis[group])
}

/**
 * Почему план строить рано — как not_ready на сервере: по потоку, который не утвердил итоги или не выгружен к ним
 * в нынешний каталог заметок (notes). Пусто — можно.
 */
export interface TasksWait { group: string; why: 'outcomes' | 'notes' }
export const tasksWaitFor = (council: Council, notes: string | null): TasksWait[] =>
  (council.streams ?? []).flatMap((stream): TasksWait[] => {
    const outcomes = stream.outcomes
    if (!outcomes?.approved) return [{ group: stream.group, why: 'outcomes' }]
    if (!stream.notes || notes === null || stream.notes.root !== notes || stream.notes.outcomes !== outcomes.run) {
      return [{ group: stream.group, why: 'notes' }]
    }
    return []
  })

/** План выгружен в нынешнюю папку задач (issues — её путь из настроек) — к нынешнему плану. */
export const tasksExported = (council: Council, issues: string | null): boolean =>
  !!council.tasks && !!council.tasks_export && issues !== null && council.tasks_export.root === issues
  && council.tasks_export.plan === council.tasks.run

/** Адрес страницы проекта. id всегда кодируется здесь, а не в местах вызова. */
export const councilPath = (id: string, stage = 'brief') => `/councils/${encodeURIComponent(id)}/${stage}`
