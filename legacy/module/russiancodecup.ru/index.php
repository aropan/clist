<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $page = curlexec($URL);
    /*
    $page = substr($page, strpos($page, "\r\n\r\n"));
    $doc = new DOMDocument();
    ini_set('error_reporting', E_ERROR);
    $doc->loadHTML($page);
    ini_set('error_reporting', E_ALL);
    $xpath = new DOMXPath($doc);
    $page = $xpath->query(".//*[@id='content']/div[1]")->item(0)->nodeValue;
    //*/

    if (!preg_match("/RCC (20[0-9]{2})\./", $page, $match)) {
        return;
    }
    $year = $match[1];

    $amonths = array("января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря");
    $replace_pairs = array();
    foreach ($amonths as $ind => $month)
    {
        $ind = sprintf("%02d", $ind + 1);
        $replace_pairs[" $month"] = ".$ind." . $year;
    }
    $page = strtr($page, $replace_pairs);

    //<tr><td>1-й квалификационный раунд</td><td style="padding: 0px 10px;"> — </td><td>19 апреля, суббота, с 12:00 до 14:00 по московскому времени. </td></tr>
    preg_match_all("#
        <tr>[^<]*
            <td[^>]*>
                (?P<title>[^<]*)
            </td>[^<]*
            <td[^>]*>[^<]*</td>[^<]*
            <td[^>]*>[^<]*?(?P<date>[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{4})(?:[^<]*(?<=с\s)(?<date_start_time>[0-9]{1,2}:[0-9]{2})[^<]*(?<=до\s)(?<date_end_time>[0-9]{1,2}:[0-9]{2}))?[^<]*
            </td>[^<]*
        </tr>
        #x", $page, $matches
    );

    foreach ($matches[0] as $i => $value)
    {
        $contests[] = array(
            'start_time' => $matches['date'][$i] . " " . $matches['date_start_time'][$i],
            'end_time' => $matches['date'][$i] . " " . $matches['date_end_time'][$i],
            'title' => $matches['title'][$i],
            'url' => $URL,
            'host' => $HOST,
            'rid' => $RID,
            'key' => $matches['date'][$i] . "\n" . $matches['title'][$i],
            'timezone' => $TIMEZONE
        );
    }

    if ($RID == -1) {
        print_r($contests);
    }
?>
