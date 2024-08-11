<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $host = parse_url($URL, PHP_URL_SCHEME) . "://" . parse_url($URL, PHP_URL_HOST);
    $change_url = $host . '/asp/champ/index.asp?main=update&mode=ch_period';
    $referer = $host . '/asp/champ/index.asp?main=stage';

    $year = date('Y');
    $skip = 0;

    do {
        $skip += 1;

        $url = $change_url;
        $page = curlexec($url, "period=$year", array('http_header' => array("Content-Type: application/x-www-form-urlencoded", "Referer: $referer")));

        preg_match('#<h1>(?P<title>[^<]*)</h1>#', $page, $match);
        if (strpos($match['title'], "$year") === false) {
            break;
        }

        if (DEBUG) {
            echo "$year - {$match['title']}\n";
        }

        preg_match_all('#<a[^>]*href="?(?P<href>[^ ">]*)"?>\[Описание\]</a>#', $page, $matches, PREG_SET_ORDER);

        foreach ($matches as $match) {
            $url = $match['href'];
            $page = curlexec($url);

            $page = str_replace("&nbsp;", " ", $page);
            $page = replace_russian_moths_to_number($page);

            preg_match('#<h1>Содержание олимпиады "(?P<title>.*?)"</h1>#', $page, $m);
            $title = $m['title'];
            preg_match('#<b[^>]*>Начало олимпиады:</b>(?P<start_time>[^<]*)<#', $page, $m);
            $start_time = $m['start_time'];
            $start_time = preg_replace('#\s*г\.\s*#', ' ', $start_time);
            preg_match('#<b[^>]*>Продолжительность:</b>(?P<duration>[^<]*)<#', $page, $m);
            $duration = $m['duration'];
            preg_match('#id_stage=(?P<id>[0-9]+)#', $url, $m);
            $key = $m['id'];

            $contests[] = array(
                'start_time' => trim($start_time),
                'duration' => trim($duration),
                'title' => trim($title),
                'host' => $HOST,
                'url' => $url,
                'timezone' => $TIMEZONE,
                'key' => $key,
                'rid' => $RID
            );
            $skip = 0;
        }

        if ($skip >= 3) {
            break;
        }

        $year -= 1;
    } while (isset($_GET['parse_full_list']));
?>
