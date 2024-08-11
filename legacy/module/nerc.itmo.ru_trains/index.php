<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $page = curlexec($URL);
    if (!preg_match("#(?<date>(?:January|February|March|April|May|June|July|August|September|October|November|December)\s*\d+\W*\d{4})#", $page, $matches)) return;
    $start_time = strtotime($matches['date'] . " 16:30");
    $title = 'NRU ITMO Training';
    for ($i = 0; $i < 10; $i++)
    {
        $day = date('l', $start_time);
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
