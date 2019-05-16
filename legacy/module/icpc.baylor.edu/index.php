<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "https://icpc.baylor.edu/worldfinals/schedule";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'UTC';
    if (!isset($contests)) $contests = array();

    $page = curlexec($URL);
    if (!preg_match("#>The (?P<year>[0-9]{4}) (?P<title>ACM-ICPC World Finals)#i", $page, $match)) {
        return;
    }
    $year = $match["year"];
    $title = $match["title"];
    if (!preg_match("#>hosted by[^,]*,\s*(?P<where>[^<]*?)\s*<#i", $page, $match)) {
        return;
    }
    $title .= ". " . $match["where"];
    if (!preg_match_all("#<strong>\s*(?P<date>[^\s]+\s+[^\s]+\s+[0-9]+)\s*-#", $page, $matches)) {
        return;
    }
    $start_time = reset($matches['date']) . " " . $year;
    $end_time = end($matches['date']) . " " . $year;

    $contests[] = array(
        'start_time' => $start_time,
        'end_time' => $end_time,
        'title' => $title,
        'url' => $URL,
        'host' => $HOST,
        'key' => $title . ' ' . $year,
        'rid' => $RID,
        'timezone' => $TIMEZONE
    );

    if ($RID == -1) {
        print_r($contests);
    }
?>
