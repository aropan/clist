<?php

require_once dirname(__FILE__) . '/../../config.php';

global $URL, $RID, $HOST, $TIMEZONE, $contests;

$page = curlexec($URL);
$text = html_entity_decode(strip_tags($page), ENT_QUOTES | ENT_HTML5, 'UTF-8');
$text = preg_replace('/\s+/', ' ', $text);

$timezone = new DateTimeZone($TIMEZONE);

preg_match_all(
    '#Preliminary Round\s+(?P<round>\d+)\s+(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+20\d{2})#',
    $text,
    $matches,
    PREG_SET_ORDER
);

foreach ($matches as $match) {
    $start = DateTime::createFromFormat('F j, Y H:i', $match['date'] . ' 07:30', $timezone);
    if (!$start) {
        continue;
    }

    $end = clone $start;
    $end->modify('+1 day')->setTime(23, 0);

    $contests[] = [
        'start_time' => $start->format('Y-m-d H:i:s'),
        'end_time' => $end->format('Y-m-d H:i:s'),
        'title' => 'USIOT Preliminary Round ' . $match['round'],
        'url' => $URL,
        'key' => $start->format('Y-m-d') . '-round-' . $match['round'],
        'host' => $HOST,
        'timezone' => $TIMEZONE,
        'rid' => $RID,
    ];
}

if (preg_match('#National Finals\s+(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+20\d{2})#', $text, $match)) {
    $start = DateTime::createFromFormat('F j, Y H:i', $match['date'] . ' 00:00', $timezone);
    if ($start) {
        $end = clone $start;
        $end->setTime(23, 59, 59);

        $contests[] = [
            'start_time' => $start->format('Y-m-d H:i:s'),
            'end_time' => $end->format('Y-m-d H:i:s'),
            'title' => 'USIOT National Finals',
            'url' => $URL,
            'key' => $start->format('Y-m-d') . '-national-finals',
            'host' => $HOST,
            'timezone' => $TIMEZONE,
            'rid' => $RID,
        ];
    }
}

if (preg_match(
    '#IIOT International Finals\s+(?P<start_month>[A-Z][a-z]+)\s+(?P<start_day>\d{1,2})-(?P<end_month>[A-Z][a-z]+)\s+(?P<end_day>\d{1,2}),\s*(?P<year>20\d{2})#',
    $text,
    $match
)) {
    $start = DateTime::createFromFormat(
        'F j, Y H:i',
        $match['start_month'] . ' ' . $match['start_day'] . ', ' . $match['year'] . ' 00:00',
        $timezone
    );
    $end = DateTime::createFromFormat(
        'F j, Y H:i:s',
        $match['end_month'] . ' ' . $match['end_day'] . ', ' . $match['year'] . ' 23:59:59',
        $timezone
    );

    if ($start && $end) {
        $contests[] = [
            'start_time' => $start->format('Y-m-d H:i:s'),
            'end_time' => $end->format('Y-m-d H:i:s'),
            'title' => 'IIOT ' . $match['year'] . ' International Finals',
            'url' => $URL,
            'key' => $match['year'] . '-iiot-international-finals',
            'host' => $HOST,
            'timezone' => $TIMEZONE,
            'rid' => $RID,
        ];
    }
}
