<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $debug_ = $RID == -1;

    $urls = [];
    foreach(array($URL, 'http://icfpcontest.org/') as $url) {
        $page = curlexec($url);
        if (in_array($url, $urls)) {
            continue;
        }
        $urls[] = $url;

        if (!preg_match('#contest will start(?:\s*at|\s*on)\s*(?:<a[^>]*>)?(?P<start_time>[^<.]{4,})#', $page, $match)) {
            if (!preg_match('#<script[^>]*src="(?P<url>/static/js/main\.[^"]*\.js)"[^>]*>#', $page, $match)) {
                continue;
            }
            $js = curlexec($match['url']);
            if (!preg_match('#"on\s*(?P<start_time>[^,"]*,[^@"]*@[^"]*)"#', $js, $match)) {
                continue;
            }
        }
        $start_time = preg_replace('/\s+(?:at|@)/', '', $match['start_time']);

        if (preg_match_all('#(?P<title>\b[\s*a-z]*)\s*will end(?:\s*at|\s*on)\s*(?:<a[^>]*>)?(?P<end_time>[^<.]*)#', $page, $matches, PREG_SET_ORDER)) {
            foreach ($matches as $m) {
                $title = ucfirst(trim($m['title']));
                $end_time = preg_replace('/\s+at/', '', $m['end_time']);
                $contests[] = array(
                    'start_time' => $start_time,
                    'end_time' => $end_time,
                    'title' => $title,
                    'url' => $url,
                    'host' => $HOST,
                    'rid' => $RID,
                    'timezone' => $TIMEZONE,
                );
            }
        } else {
            $contests[] = array(
                'start_time' => $start_time,
                'duration' => '72:00',
                'title' => 'ICFP Programming Contest',
                'url' => $url,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
            );
        }
    }
    if ($debug_) {
        print_r($contests);
    }
?>
