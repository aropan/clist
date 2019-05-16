<?php
    require_once dirname(__FILE__) . '/../../config.php';

    if (!isset($URL)) $URL = 'https://opener.itransition.com/';
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'Europe/Minsk';
    if (!isset($contests)) $contests = array();

    $page = curlexec($URL);
    $page = replace_russian_moths_to_number($page);

    if (!preg_match('#<title>[^<]*(?P<year>[0-9]{4})[^<]*</title>#', $page, $match)) {
        return;
    }
    $year = $match['year'];

    if (!preg_match('/(?:Конкурс начинается|Отборочный тур)[^<0-9]*[0-9.]+[^<]* до [^<0-9]*[0-9.]+[^<]*</', $page, $match)) {
        return;
    }

    preg_match_all('/[0-9]+[.:]+[0-9.:]*[0-9]/', $match[0], $matches);
    $times = $matches[0];
    if (count($times) != 4) {
        return;
    }

    $start_time = $times[0] . ' ' . $times[1];
    $end_time = $times[2] . ' ' . $times[3];
    if (strpos($start_time, $year) === false) {
        $start_time .= " $year";
    }
    if (strpos($end_time, $year) === false) {
        $end_time .= " $year";
    }

    $title = 'Отборочный тур';

    $contests[] = array(
        'start_time' => $start_time,
        'end_time' => $end_time,
        'title' => $title,
        'url' => $URL,
        'host' => $HOST,
        'rid' => $RID,
        'timezone' => $TIMEZONE,
        'key' => $title . ' ' . $year
    );

    if ($RID === -1) {
        print_r($contests);
    }
?>
