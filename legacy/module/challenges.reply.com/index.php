<?php
    require_once dirname(__FILE__) . "/../../config.php";
    require_once dirname(__FILE__) . "/secret.php";

    $url = 'https://challenges.reply.com/tamtamy/api/user-in-session.json';
    $session = curlexec($url, null, array("json_output" => true));
    if (is_string($session) && ends_with($session, 'null')) {
        $url = "https://challenges.reply.com/tamtamy/user/signIn.action";
        $data = array(
            "username" => $CHALLENGE_REPLY_EMAIL,
            "password" => $CHALLENGE_REPLY_PASSWORD,
            "remember" => "on",
            "pageSourceType" => "MODAL",
        );
        $data = curlexec($url, $data, array("json_output" => true));
        if (!isset($data["message"])) {
            trigger_error("Invalid singin: $data", E_USER_WARNING);
            return;
        } else if (!isset($data["message"]) || strpos(strtolower($data["message"]), "success") === false) {
            trigger_error("Invalid singin: {$data['message']}", E_USER_WARNING);
            return;
        }
        $url = 'https://challenges.reply.com/tamtamy/api/user-in-session.json';
        $session = curlexec($url, null, array("json_output" => true));
    }
    unset($CHALLENGE_REPLY_EMAIL);
    unset($CHALLENGE_REPLY_PASSWORD);

    $keys = array();
    if (isset($session['roles'])) {
        foreach ($session['roles'] as $role) {
            $category = slugify($role['challengeCategory']);
            $keys[$category] = $role['challengeId'];
        }
    }

    $page = curlexec($URL);
    preg_match_all('#<a[^>]*href="(?P<url>[^"]*/challenges/[^"]*/home/?)"[^>]*>#', $page, $matches);
    $challenges_urls = array_unique($matches['url']);
    foreach ($challenges_urls as $url) {
        $url = url_merge($URL, $url);
        $page = curlexec($url);

        if (!preg_match('#/challenges/(?P<category>[^/]*)/#', $url, $match)) {
            continue;
        }
        $category = $match['category'];
        $category = slugify($category);

        if (!preg_match('#<[^>]*class="[^"]*infobox[^"]*"[^>]*>Info(?:\s*<[^>]*>)*(?P<date>[^<]*)(?:\s*<[^>]*>)*(?P<time>[^<]*)#', $page, $match)) {
            continue;
        }

        $date = $match['date'];
        $time = $match['time'];

        if (!preg_match('#(?P<year>[0-9]{4})#', $date, $match)) {
            continue;
        }
        $year = $match['year'];

        if (!preg_match_all('#[0-9]+:[0-9]+#', $time)) {
            continue;
        }


        $times = preg_split('#[^0-9]*[–-][^0-9]*#', $time);
        if (count($times) == 1) {
            $start_time = $date . " " . $time;
            $end_time = $date . " " . $time;
        } else {
            list($start_time, $end_time) = $times;
            $start_time = explode(' ', trim($start_time));
            $end_time = explode(' ', trim($end_time));
            if (count($start_time) < count($end_time)) {
                $start_time = array_merge($start_time, array_slice($end_time, count($start_time)));
            }
            $start_time = $date . ' ' . implode(' ', $start_time);
            $end_time = $date . ' ' . implode(' ', $end_time);
        }

        preg_match('#<title[^>]*>(?P<title>[^\|<]*)#', $page, $match);
        $title = trim($match['title']);

        $old_key = null;
        $key = $title . ' ' . $year;
        if (isset($keys[$category])) {
            $old_key = $key;
            $key = $keys[$category];
        }

        $contests[] = array(
            'start_time' => $start_time,
            'end_time' => $end_time,
            'title' => $title,
            'url' => $url,
            'old_key' => $old_key,
            'key' => $key,
            'host' => $HOST,
            'rid' => $RID,
            'timezone' => $TIMEZONE,
        );
    };
?>
