<?php
    require_once dirname(__FILE__) . "/../../config.php";

    // $url = 'http://web.archive.org/web/20200921040502/https://www.techgig.com/codegladiators/schedule';
    // $url = 'http://web.archive.org/web/20211021094028/https://www.techgig.com/codegladiators/schedule';
    // $url = 'http://web.archive.org/web/20220818085257/https://www.techgig.com/codegladiators/schedule';
    $url = 'https://www.techgig.com/codegladiators/schedule';
    $host = 'techgig.com/codegladiators';
    $contest_page = curlexec($url);
    $contest_page = preg_replace('#<--.*?-->#', '', $contest_page);

    preg_match('#Code Gladiators [0-9]{4}#', $contest_page, $match);
    $main_title = $match[0];

    preg_match_all('#
        <h4[^>]*class="btngroup4"[^>]*>.*?
        <span[^>]*class="fctrl"[^>]*>(?P<date>[^<]*)</span>\s*</h4>.*?
        <h4[^>]*class="nomargin"[^>]*>(?P<title>[^<]*)</h4>
    #xs', $contest_page, $matches, PREG_SET_ORDER);

    foreach ($matches as $match) {
        $title = $match['title'];
        $short_title = preg_replace('#:.*#', '', $title);
        if (($short_title != 'Finale' && stripos($title, 'coding') === false) || stripos($title, 'shortlist') !== false) {
            continue;
        }
        $date = $match['date'];
        $date = preg_replace('#&amp;#', '&', $date);

        if (strpos($date, '&') !== false) {
            $date = trim(preg_replace('#.*&#', '', $date));
            if (preg_match('#Coding\s*\(([^\)]*)\)#', $title, $match)) {
                $parts = explode(' ', $date);
                $parts[0] = $match[1];
                $date = implode(' ', $parts);
            }
        }
        $title = $main_title . '. ' . $short_title;

        if (preg_match('#\s+-\s+#', $date)) {
            $times = preg_split('#\s*-\s*#', $date, 2);
            $start_times = preg_split('#,\s+#', $times[0]);
            $end_times = preg_split('#,\s+#', $times[1]);
            $start_time = implode(', ', $start_times + $end_times);
            $end_time = implode(', ', $end_times + $start_times);
        } else {
            $start_time = $date;
            $end_time = $date;
        }
        $start_time = preg_replace('#[\s,]+#', ' ', $start_time);;
        $end_time = preg_replace('#[\s,]+#', ' ', $end_time);;

        $contests[] = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'title' => $title,
            'url' => $url,
            'key' => slugify($title),
            'host' => $host,
            'timezone' => $TIMEZONE,
            'rid' => $RID,
        );
    }
?>
