import http from 'k6/http';
import encoding from 'k6/encoding';
import exec from 'k6/execution';
import { Counter, Gauge, Trend } from 'k6/metrics';

const mode = __ENV.MODE || 'mixed';
const rate = Number(__ENV.RATE || 1);
const seconds = Number(__ENV.SECONDS_PER_STEP || 30);
const port = Number(__ENV.APP_PORT || 8082);
const base = 'http://127.0.0.1:' + port;
const authorization = 'Basic ' + encoding.b64encode(
    (__ENV.DEMO_USERNAME || 'demo') + ':' + (__ENV.DEMO_PASSWORD || 'demo123')
);
const profile = [
    {name: 'meta', weight: 5},
    {name: 'list', weight: 39},
    {name: 'detail', weight: 30},
    {name: 'create', weight: 9},
    {name: 'status', weight: 7},
    {name: 'comment', weight: 8},
    {name: 'summary', weight: 2},
];

if (!['mixed', 'heavy'].includes(mode) || !Number.isInteger(rate) || rate < 1
    || !Number.isInteger(seconds) || seconds < 1 || !Number.isInteger(port) || port < 1
    || port > 65535 || profile.reduce((sum, op) => sum + op.weight, 0) !== 100) {
    throw new Error('Проверьте MODE, RATE, SECONDS_PER_STEP, APP_PORT и веса профиля.');
}

const openedAt = new Gauge('stage_start_epoch_ms');
const attemptsInWindow = new Counter('completed_in_window');
const successesInWindow = new Counter('successful_in_window');
const serverTime = new Trend('server_ms', true);
const dbTime = new Trend('db_ms', true);
const applicationTime = new Trend('outside_sql_ms', true);
const queryCount = new Trend('sql_queries');
const expectOK = http.expectedStatuses(200);
const expectCreated = http.expectedStatuses(201);
const scenarioTag = '{scenario:' + mode + '}';

export const options = {
    discardResponseBodies: true,
    summaryTrendStats: ['med', 'p(95)', 'max'],
    systemTags: ['name', 'method', 'status', 'scenario', 'expected_response', 'error_code'],
    scenarios: {
        [mode]: {
            executor: 'constant-arrival-rate',
            rate,
            timeUnit: '1s',
            duration: seconds + 's',
            preAllocatedVUs: Math.min(512, Math.max(16, rate * 12)),
            gracefulStop: '15s',
            exec: mode,
        },
    },
    thresholds: {
        ['http_req_duration' + scenarioTag]: ['p(95)<500'],
        ['http_req_failed' + scenarioTag]: ['rate<0.01'],
    },
};

export function setup() {
    const reply = http.get(base + '/api/meta', {
        headers: {Authorization: authorization},
        responseCallback: expectOK,
        redirects: 0,
        timeout: '10s',
        tags: {name: 'auth_check'},
    });
    if (reply.status !== 200) {
        exec.test.abort('Проверка Basic-авторизации до ступени вернула HTTP ' + reply.status);
    }
}

function operationFor(iteration) {
    let position = (iteration * 37 + 11) % 100;
    for (const op of profile) {
        if (position < op.weight) return op.name;
        position -= op.weight;
    }
}

function call(name, method, path, body = null) {
    const creating = method === 'POST';
    const reply = http.request(method, base + path, body && JSON.stringify(body), {
        headers: {Authorization: authorization, 'Content-Type': 'application/json'},
        tags: {name},
        responseCallback: creating ? expectCreated : expectOK,
        redirects: 0,
        timeout: '12s',
    });
    const inWindow = Date.now() < exec.scenario.startTime + seconds * 1000;
    attemptsInWindow.add(Number(inWindow));
    successesInWindow.add(Number(inWindow && reply.status === (creating ? 201 : 200)));

    const server = reply.headers['X-Server-Ms'];
    const sql = reply.headers['X-Db-Ms'];
    const queries = reply.headers['X-Db-Queries'];
    if (server !== undefined && sql !== undefined && queries !== undefined) {
        const tags = {name};
        serverTime.add(Number(server), tags);
        dbTime.add(Number(sql), tags);
        applicationTime.add(Math.max(0, Number(server) - Number(sql)), tags);
        queryCount.add(Number(queries), tags);
    }
}

export function mixed() {
    const iteration = exec.scenario.iterationInTest;
    if (iteration === 0) openedAt.add(exec.scenario.startTime);
    const ticket = 1 + ((iteration * 7919 + 104729) % 75000);
    const category = 1 + iteration % 10;
    const requester = 2 + iteration % 2999;
    switch (operationFor(iteration)) {
        case 'meta':
            return call('meta', 'GET', '/api/meta');
        case 'list': {
            const filter = ['&status=new', '&status=new&category_id=' + category, ''][iteration % 3];
            return call('list', 'GET', '/api/tickets?page=1&size=20' + filter);
        }
        case 'detail':
            return call('detail', 'GET', '/api/tickets/' + ticket);
        case 'create':
            return call('create', 'POST', '/api/tickets', {
                user_id: requester,
                category_id: category,
                title: 'keppel_yura. Заявка нагрузочного прогона',
                body: 'Обращение клиента в ходе испытания ДЗ 2',
            });
        case 'status':
            return call('status', 'PATCH', '/api/tickets/' + ticket + '/status', {
                status: iteration % 2 ? 'in_progress' : 'closed',
            });
        case 'comment':
            return call('comment', 'POST', '/api/tickets/' + ticket + '/comments', {
                author_id: 1,
                body: 'keppel_yura. Ответ сотрудника службы поддержки',
            });
        case 'summary':
            return call('summary', 'GET', '/api/summary');
    }
}

export function heavy() {
    if (exec.scenario.iterationInTest === 0) openedAt.add(exec.scenario.startTime);
    call('summary', 'GET', '/api/summary');
}

export function handleSummary(data) {
    return { [__ENV.SUMMARY_PATH || 'summary.json']: JSON.stringify(data, null, 2) };
}
