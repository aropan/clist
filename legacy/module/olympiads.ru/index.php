<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $page = curlexec($URL);
    if (!preg_match('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>\s*Информация\s*об\s*олимпиаде\s*</a>#', $page, $match)) {
        return;
    }
    $page = curlexec($match['url']);

    $amonths = array("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря");
    $replace_pairs = array();
    foreach ($amonths as $ind => $month)
    {
        $ind = sprintf("%02d", $ind + 1);
        $replace_pairs[" $month "] = ".$ind.";
    }
    $page = strtr($page, $replace_pairs);

    if (!preg_match('#<h4\s*align="center">(?<title>[^<]*)</h4>\s*<p\s*class="header">#', $page, $match)) {
        return;
    }
    list($main_title, $season) = explode(",", $match['title']);
    $main_title = trim($main_title);
    $season = str_replace("/", "-20", explode(" ", trim($season))[0]);

    preg_match_all("#
        [^0-9\.]+(?P<start_time>(?:(?:[0-9]+\.){2}[0-9]+|[0-9]+(?=-|\s*по)))
        [^0-9\.,]+(?P<end_time>(?:[0-9]+\.){2}[0-9]+)
        #x",
        $page,
        $matches
    );

    $titles = ["Заочный длинный этап", "Заочный короткий тур", "Заключительный очный этап"];
    foreach ($matches[0] as $i => $value)
    {
        $start_time = $matches["start_time"][$i];
        $end_time = $matches["end_time"][$i];
        if (is_numeric($start_time)) {
            $a = explode(".", $end_time);
            $a[0] = $start_time;
            $start_time = implode(".", $a);
        }
        $duration = strtotime($end_time) - strtotime($start_time) + 24 * 60 * 60;
        $title = $titles[$i];

        $contests[] = array(
            "start_time" => $start_time,
            "duration" => $duration / 60,
            "title" => $title . ". " . $main_title,
            "url" => $URL,
            "host" => $HOST,
            "key" => $season . ". " . $title,
            "rid" => $RID,
            "timezone" => $TIMEZONE
        );
    }

    if ($RID == -1) {
        print_r($contests);
    }
?>
