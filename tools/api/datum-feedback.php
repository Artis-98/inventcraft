<?php
// Public endpoint: POST /datum-feedback.php
//
// The Suggest button in InventCraft. A suggestion or a problem report
// lands on the admin board as a card under "Reddit suggestions" (task 73),
// priority low, so it is on the board for us and off the public "Coming
// next" list until somebody decides to promise it.
//
// Body (JSON): kind ("suggestion" or "problem"), text, email (optional),
// version, os. Nothing else is stored. A few per hour from one address,
// and short, so the board cannot be flooded.
//
// Lives in the DATUM repository at tools/api/, uploaded to the root of
// api.iiteg.com beside datum-upcoming.php, whose config.php it shares.

header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');
header('Content-Type: application/json; charset=utf-8');
if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') {
    http_response_code(204);
    exit;
}
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    http_response_code(405);
    echo json_encode(['error' => 'POST only']);
    exit;
}

require_once __DIR__ . '/config.php';

const FEEDBACK_PARENT = 73;
const FEEDBACK_PER_HOUR = 6;

function fb_out(int $code, array $body): void {
    http_response_code($code);
    echo json_encode($body, JSON_UNESCAPED_UNICODE);
    exit;
}

// a few an hour from one address, counted in a file outside the web root
$ip = (string)($_SERVER['REMOTE_ADDR'] ?? '');
$stamp = sys_get_temp_dir() . '/datum-feedback-' . hash('sha256', $ip) . '.json';
$recent = [];
if (is_file($stamp)) {
    $recent = json_decode((string)@file_get_contents($stamp), true) ?: [];
}
$now = time();
$recent = array_values(array_filter($recent, static fn($t) => $now - (int)$t < 3600));
if (count($recent) >= FEEDBACK_PER_HOUR) {
    fb_out(429, ['error' => 'too many from here; try again in an hour']);
}

$raw = file_get_contents('php://input', false, null, 0, 20000);
$in = json_decode((string)$raw, true);
if (!is_array($in)) fb_out(400, ['error' => 'send JSON']);

$text = trim((string)($in['text'] ?? ''));
if ($text === '' || mb_strlen($text) > 4000) {
    fb_out(422, ['error' => 'the message must be 1 to 4000 characters']);
}
$kind = (($in['kind'] ?? '') === 'problem') ? 'problem' : 'suggestion';
$email = trim((string)($in['email'] ?? ''));
if ($email !== '' && !filter_var($email, FILTER_VALIDATE_EMAIL)) $email = '';
$version = mb_substr(preg_replace('/[^0-9A-Za-z.\- ]/', '', (string)($in['version'] ?? '')), 0, 40);
$os = mb_substr(preg_replace('/[^0-9A-Za-z.\-_ ()]/', '', (string)($in['os'] ?? '')), 0, 80);

$first = preg_replace('/\s+/', ' ', $text);
$title = ($kind === 'problem' ? 'Problem: ' : 'Suggestion: ')
       . mb_substr($first, 0, 80) . (mb_strlen($first) > 80 ? '...' : '');
$description = "From the Suggest button in InventCraft"
             . ($version !== '' ? " $version" : '')
             . ($os !== '' ? " on $os" : '') . ".\n"
             . ($email !== '' ? "Reply to: $email\n" : "No email given.\n")
             . "\n" . $text;

try {
    $pdo = db();
    $parent = $pdo->prepare('SELECT space_id FROM ws_tasks WHERE id = ?');
    $parent->execute([FEEDBACK_PARENT]);
    $spaceId = $parent->fetchColumn();
    if ($spaceId === false) fb_out(500, ['error' => 'unavailable']);
    $st = $pdo->prepare(
        'INSERT INTO ws_tasks (space_id, title, description, status, priority, due_date, parent_id, sort_order, project_no, item_no)
         VALUES (?, ?, ?, ?, ?, NULL, ?, 0, NULL, NULL)'
    );
    $st->execute([$spaceId, mb_substr($title, 0, 500), $description,
                  'todo', 'low', FEEDBACK_PARENT]);
    $recent[] = $now;
    @file_put_contents($stamp, json_encode($recent));
    fb_out(200, ['ok' => true]);
} catch (Throwable $e) {
    error_log('datum-feedback: ' . $e->getMessage());
    fb_out(500, ['error' => 'unavailable']);
}
