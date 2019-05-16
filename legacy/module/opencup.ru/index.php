<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "http://opencup.ru/";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'Europe/Moscow';
    if (!isset($contests)) $contests = array();

    $debug_ = $RID == -1;

    $url = $URL;
    $page = curlexec($url);
    if (!preg_match('#<a[^>]*href="(?P<url>[^"]*schedule[^"]*)"[^>]*>#', $page, $match)) {
        return;
    }
    $url = $match['url'];
    if (parse_url($url, PHP_URL_HOST) == "") {
        $url = 'http://' . parse_url($URL, PHP_URL_HOST) . "/" . $url;
    }

    if ($debug_) {
        echo "url = $url\n";
    }
    $page = curlexec($url);
    $URL = $url;

    preg_match_all('#
        <li>[^<]*
            <a[^>]*>(?<title>[^<]*GP[^<]*)\s\&\#
        .*?
        <li><a[^>]*href="(?<url>[^"]*)">1st\sDiv\sResults</a></li>
        #xs', $page, $matches
    );
    $results = array();
    foreach ($matches[0] as $i => $value)
    {
        $url = $matches['url'][$i];
        if (parse_url($url, PHP_URL_HOST) == "")
        {
            $url = parse_url($URL, PHP_URL_SCHEME) . "://" . "$HOST" . "/$url";
        }
        $title = $matches['title'][$i];
        $title = str_replace('GP', 'Grand Prix', $title);
        $results[$title] = $url;
    }

    preg_match_all('#</td><td>(?<date>\d\d\.\d\d\.\d\d\d\d)</td><td>[^0-9]*(?<date_start_time>\d\d:\d\d).*?</td><td>(?<title>.*?)</td></tr>#s', $page, $matches, PREG_SET_ORDER);
    $year = "";
    foreach ($matches as $match)
    {
        $title = trim(strip_tags($match['title']));
        $words = explode(" ", $title);
        $opt = strlen($title);
        $titles = explode(" of ", $title);
        $q = end($titles);
        foreach ($results as $t => $u) {
            $ts = explode(" of ", $t);
            $p = end($ts);
            $res = levenshtein($p, $q);
            if ($res < $opt) {
                $opt = $res;
                $url = $u;
                $tit = $t;
            }
        }
        if ($opt < 4) {
            unset($results[$tit]);
        } else {
            $url = $URL;
        }
        $start_time = trim(strip_tags($match['date'])) . " " . trim(strip_tags($match['date_start_time']));
        if (empty($year)) {
            $year = date('Y', strtotime($start_time));
        }
        $contests[] = array(
            'start_time' => $start_time,
            'duration' => "05:00",
            'title' => $title,
            'url' => $url,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $year . '-' . ($year + 1) . ' ' . $title
        );
    }
    count($results) && trigger_error('No empty results list after parsing', E_USER_WARNING);
?>
