<?php
    require_once dirname(__FILE__) . '/../../config.php';

    if (!isset($URL)) $URL = 'https://adventofcode.com/';
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'UTC';
    if (!isset($contests)) $contests = array();

    $page = curlexec($URL);
    if (!preg_match('/server_eta\s*=\s*(?<eta>[0-9]+)/', $page, $match)) {
        return;
    }
    $eta = intval($match['eta']);

    if (!preg_match('#<title>(?<title>[^<]*)</title>#', $page, $match)) {
        return;
    }
    $title = $match['title'];

    if (!preg_match('#day-?(?<day>[0-9]+).*day-new#', $page, $match)) {
        return;
    }
    $day = $match['day'];

    $start_time = time() + $eta;
    $start_time = round($start_time / 60) * 60;
    $end_time = $start_time + 24 * 60 * 60;
    $title .= '. Day ' . $day;

    $contests[] = array(
        'start_time' => $start_time,
        'end_time' => $end_time,
        'title' => $title,
        'url' => $URL,
        'host' => $HOST,
        'rid' => $RID,
        'timezone' => $TIMEZONE,
        'key' => $title
    );

    if ($RID === -1) {
        print_r($contests);
    }
?>
