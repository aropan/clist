<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "http://acm.zju.edu.cn/onlinejudge/showContests.do";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 28880;
    if (!isset($contests)) $contests = array();

    $page = curlexec($URL);

    preg_match_all('#<tr class="row[^"]*">[^<]*<td class="[^"]*">[^<]*<a href="(?<url>[^"]*)">[^<]*<font[^>]*>(?<title>[^<]*)</font>[^<]*</a>[^<]*</td>[^<]*<td[^>]*>[^<]*<a[^>]*>[^<]*<font[^>]*>(?<start_time>[^(]*)[^<]*</font>#s', $page, $matches);

    foreach ($matches[0] as $i => $value)
    {
        $url = parse_url($URL, PHP_URL_SCHEME) . '://' . $HOST . trim($matches['url'][$i]);
        $page = curlexec($url);

        preg_match('#Length:</td>[^<]*<td>(?<duration>[^<]*)</td>#s', $page, $match);
        $duration = $match['duration'];

        $contests[] = array(
            'start_time' => trim($matches['start_time'][$i]),
            'duration' => $duration,
            'title' => trim($matches['title'][$i]),
            'url' => $url,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
            'key' => $url
        );
    }

    if ($RID == -1) {
        print_r($contests);
    }
?>
