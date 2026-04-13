# UML Диаграммы проекта MAX AI Dashboard

---

## 1. UML Database Diagram (ER-диаграмма)

```plantuml
@startuml Database_Schema

!theme plain

entity "messages.db" as db1 {
  * messages
  --
  * id : PK, INT, AUTOINCREMENT
  * message_id : INT
  * channel_id : INT
  * channel_name : TEXT
  * text : TEXT (NULL)
  * link : TEXT
  * timestamp : INT (unix)
  * date : TEXT (ISO)
  --
  UNIQUE(message_id, channel_id)
}

entity "analytics.db" as db2 {
  * actionable_posts
  --
  * id : PK, INT, AUTOINCREMENT
  * message_id : INT
  * channel_id : INT
  * channel_name : TEXT
  * text : TEXT (NULL)
  * link : TEXT
  * timestamp : INT (unix)
  * date : TEXT (ISO)
  * requires_response : INT (0/1)
  * category : TEXT (enum)
  * urgency : TEXT (low/medium/high)
  * reason : TEXT
  * draft_reply_thesis : TEXT (NULL)
  * ai_raw_response : TEXT (JSON)
  * analyzed_at : TEXT (ISO)
  * status : TEXT (new/in_progress/resolved/ignored)
  --
  UNIQUE(message_id, channel_id)
  INDEX idx_urgency (urgency)
  INDEX idx_status (status)
  INDEX idx_date (date)
  INDEX idx_actionable_category (category)
}

entity "analytics.db" as db3 {
  * dashboard_users
  --
  * id : PK, INT, AUTOINCREMENT
  * username : TEXT (UNIQUE)
  * password : TEXT (bcrypt hash)
  * role : TEXT (default 'admin')
  * created_at : TEXT (default now)
}

db1 .u.-right-> db2 : "message_id +\nchannel_id reference"
db3 .. db2 : "shared DB file"

note top of db1
  Заполняется парсером (Parser/comment_parser.py)
  Каждая 30 сек polling -> INSERT OR IGNORE
end note

note top of db2
  Заполняется AI-сервером (AI/analytics_server.py)
  Webhook от парсера -> LLM анализ -> INSERT
  Используется FastAPI + Express (shared access, WAL mode)
end note

note top of db3
  Управляется Dashboard Server (Express)
  Seed: admin/admin (bcrypt)
  JWT аутентификация
end note

@enduml
```

---

## 2. UML Component/Logic Diagram (Логика работы программы)

```plantuml
@startuml Component_Logic

!theme plain

skinparam componentStyle rectangle

package "MAX MESSENGER" as MAX #LightBlue
package "PARSER (Python)" as Parser #LightYellow
package "AI SERVER (FastAPI)" as AI #LightCoral
package "DASHBOARD SERVER (Express)" as DashboardServer #LightGreen
package "DASHBOARD CLIENT (React)" as DashboardClient #LightSteelBlue

MAX -right-> Parser : PyMax API\npolling каждые 30сек
Parser -down-> AI : POST /webhook/post\n(aiohttp, 2 retry)
AI -right-> DashboardServer : Shared analytics.db\n(WAL mode)
DashboardServer -down-> DashboardClient : REST API\n(CORS, JWT auth)

component Parser {
  [UserBot Auth\n(phone)] as auth
  [Channel Resolver] as channels
  [Polling Loop\n(30s)] as poll
  [Message Fetch\n(last 5)] as fetch
  [Deduplication\n(INSERT OR IGNORE)] as dedup
  [SQLite Writer\n(messages.db)] as db_writer
  [Webhook Client\n(retry x2, 5s delay)] as webhook
  
  auth -> channels
  channels -> poll
  poll -> fetch
  fetch -> dedup
  dedup -> db_writer
  dedup -> webhook
}

component AI {
  [Webhook Endpoint\nPOST /webhook/post] as wh
  [Pydantic Validator] as validate
  [Empty Text Filter] as filter
  [LLM Client\n(OpenRouter Qwen3.6)] as llm
  [Semaphore\n(max 3 parallel)] as semaphore
  [JSON Parser] as json_parser
  [DB Writer\n(actionable_posts)] as ai_db
  [Stats Endpoint\nGET /stats] as stats
  [CRUD Endpoints\nGET/PATCH /actionable/:id] as crud
  
  wh -> validate
  validate -> filter
  filter -> semaphore
  semaphore -> llm
  llm -> json_parser
  json_parser -> ai_db
  
  stats .. ai_db
  crud .. ai_db
}

component DashboardServer {
  [Auth Routes\n/register, /login] as auth_routes
  [JWT Middleware] as jwt
  [Post Routes\nGET /posts, DELETE /posts/:id] as post_routes
  [SQLite Access\n(better-sqlite3)] as express_db
  [Bcrypt Hasher] as bcrypt
  [JWT Signer\n(24h expiry)] as jwt_sign
  [Seed Admin\nadmin/admin] as seed
  
  auth_routes -> bcrypt
  auth_routes -> jwt_sign
  auth_routes -> seed
  post_routes -> jwt
  post_routes -> express_db
}

component DashboardClient {
  [Login Page] as login
  [Register Page] as register
  [Dashboard Page\n(table + filters)] as dashboard
  [AuthContext\n(localStorage + JWT)] as auth_ctx
  [API Client\n(Axios interceptors)] as api
  [Protected Route\n(guard)] as guard
  
  login -> auth_ctx
  register -> auth_ctx
  auth_ctx -> api
  guard -> auth_ctx
  dashboard -> api
}

note bottom of Parser
  messages.db -> webhook -> AI Server
  Fail-safe: при ошибке AI парсер НЕ падает
end note

note bottom of AI
  LLM: qwen/qwen3.6-plus:free
  temp=0.1, max_tokens=500
  Rate limit 429 -> skip post
end note

note bottom of DashboardServer
  CORS enabled
  Limit 200 posts
  Sort by urgency (high first)
end note

note bottom of DashboardClient
  Vite proxy /api -> :5000
  Color badges: high=red, med=yellow, low=green
end note

@enduml
```

---

## 3. UML Use Case Diagram (Действия пользователя)

```plantuml
@startuml Use_Case_Diagram

!theme plain

left to right direction

actor "Пользователь\n(Администратор)" as User #LightYellow
actor "Система\n(Automated)" as System #LightBlue

rectangle "MAX AI Dashboard" {
  
  usecase "UC1: Регистрация\nаккаунта" as UC1
  usecase "UC2: Аутентификация\n(логин/пароль)" as UC2
  usecase "UC3: Просмотр таблицы\nинцидентов" as UC3
  usecase "UC4: Фильтрация по\nкатегории" as UC4
  usecase "UC5: Фильтрация по\nсрочности" as UC5
  usecase "UC6: Сброс фильтров" as UC6
  usecase "UC7: Удаление\nинцидента" as UC7
  usecase "UC8: Выход из\nсистемы" as UC8
  usecase "UC9: Просмотр статистики\n(через API)" as UC9
  usecase "UC10: Обновление статуса\nинцидента (через API)" as UC10
  
  usecase "UC-AUTO-1: Парсинг\nканалов MAX" as UC_AUTO1
  usecase "UC-AUTO-2: AI-анализ\nпостов" as UC_AUTO2
  usecase "UC-AUTO-3: Классификация\n(категория + срочность)" as UC_AUTO3
  usecase "UC-AUTO-4: Генерация\nтезиса ответа" as UC_AUTO4
}

User --> UC1
User --> UC2
User --> UC3
User --> UC4
User --> UC5
User --> UC6
User --> UC7
User --> UC8
User --> UC9
User --> UC10

System --> UC_AUTO1
System --> UC_AUTO2
System --> UC_AUTO3
System --> UC_AUTO4

UC2 ..> UC3 : <<include>>
UC3 ..> UC4 : <<extend>>
UC3 ..> UC5 : <<extend>>
UC4 ..> UC6 : <<extend>>
UC7 ..> UC3 : <<include>> : подтверждение

UC_AUTO1 ..> UC_AUTO2 : <<include>>
UC_AUTO2 ..> UC_AUTO3 : <<include>>
UC_AUTO2 ..> UC_AUTO4 : <<include>>

note top of UC1
  Логин >= 3 символов
  Пароль >= 3 символа
  Bcrypt хеширование
end note

note top of UC2
  JWT токен на 24 часа
  Хранение в localStorage
  Авто-редирект при 401
end note

note right of UC3
  Сортировка по срочности
  (high -> medium -> low)
  Лимит 200 записей
  Цветные бейджи
end note

note right of UC7
  Требуется подтверждение
  (window.confirm)
  Физическое удаление из БД
end note

note bottom of UC_AUTO1
  PyMax UserBot API
  Polling каждые 30 сек
  Последние 5 сообщений
  Дедупликация по message_id
end note

note bottom of UC_AUTO2
  OpenRouter API
  Модель: qwen/qwen3.6-plus:free
  Temperature 0.1
  Semaphore max 3
end note

note bottom of UC_AUTO3
  Категории: ЖКХ, Дороги,
  Благоустройство, Безопасность,
  ЧП, Экология, Транспорт,
  Обращение к власти, Другое
  
  Срочность: low, medium, high
end note

note bottom of UC_AUTO4
  Черновик ответа для
  администрации
  Сохраняется в draft_reply_thesis
end note

@enduml
```

---

## Краткое описание диаграмм

### 1. Database Diagram
Проект использует **2 SQLite базы**:
- **messages.db** — сырые сообщения из парсера (8 полей, уникальная пара message_id+channel_id)
- **analytics.db** — общая база для AI-сервера и Dashboard (3 таблицы: actionable_posts с индексами + dashboard_users для JWT-аутентификации)
- Связь между таблицами логическая (через message_id/channel_id), foreign key не используются
- WAL mode включён для безопасного конкурентного доступа двух серверов к одной БД

### 2. Logic Diagram
**4 основных компонента** с чётким разделением ответственности:
- **Parser** — polling MAX каждые 30 сек, дедупликация, сохранение в messages.db, webhook в AI
- **AI Server** — валидация, LLM-анализ (OpenRouter Qwen), semaphore rate limiting, сохранение actionable posts
- **Dashboard Server** — JWT auth, CRUD API для постов, bcrypt хеширование, seed admin
- **Dashboard Client** — React UI с фильтрами, цветовыми бейджами, axios interceptors, protected routes

### 3. Use Case Diagram
**10 пользовательских действий** + **4 автоматических**:
- Пользователь: регистрация, логин, просмотр инцидентов, фильтрация (категория/срочность), удаление, выход, статистика (API), обновление статуса (API)
- Система: парсинг каналов, AI-анализ, классификация (9 категорий × 3 уровня срочности), генерация тезисов ответов
