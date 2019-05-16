<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "http://neerc.ifmo.ru/trains/information/index.html";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'Europe/Moscow';
    if (!isset($contests)) $contests = array();

    $page = curlexec($URL);
    if (!preg_match("#(?<date>(?:January|February|March|April|May|June|July|August|September|October|November|December)\s*\d+\W*\d{4})#", $page, $matches)) return;
    $start_time = strtotime($matches['date'] . " 16:30");
    $title = 'NRU ITMO Training';
    for ($i = 0; $i < 10; $i++)
    {
        $day = strftime('%A', $start_time);
        if (preg_match('/Contests will be[^<]*' . $day . '/', $page)) {
            if ($start_time > time()) {
                $contests[] = array(
                    'start_time' => date('Y-m-d H:i:s', $start_time),
                    'duration' => '05:00',
                    'title' => $title,
                    'host' => $HOST,
                    'url' => $URL,
                    'timezone' => $TIMEZONE,
                    'key' => $title . date(' d.m.Y', $start_time),
                    'rid' => $RID
                );
            }
        }
        $start_time = strtotime('+1 day', $start_time);
    }
?>
