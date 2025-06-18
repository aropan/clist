<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $parse_full_list = isset($_GET['parse_full_list']);

    $seen = array();
    for ($page = 1; $page == 1 || $parse_full_list && $was_contest; $page += 1) {
        $contests_url = url_merge($URL, "?page=$page");
        $contests_page = curlexec($contests_url);

        preg_match_all('#<a[^>]*href="(?P<href>/contest/[^"]*)"[^>]*>#i', $contests_page, $contests_urls);
        $was_contest = false;
        foreach ($contests_urls['href'] as $_ => $href) {
            $contest_url = url_merge($contests_url, $href);
            $contest_page = curlexec($contest_url);
            preg_match_all('#<dt>(?P<key>[^<]*)</dt>\s*<dd>(?P<value>[^<]*|<span[^>]*data-timestamp="(?P<timestamp>[^"]*)"[^>]*>[^<]*</span>\s*)</dd>#', $contest_page, $values, PREG_SET_ORDER);

            $variables = array();
            foreach ($values as $v) {
                $key = slugify($v['key']);
                $value = trim($v["timestamp"] ?? $v['value']);
                $variables[$key] = $value;
            }
            if (!isset($variables['start-at']) || !isset($variables['end-at'])) {
                trigger_error("Failed to find start or end time in " . $contest_url, E_USER_WARNING);
                continue;
            }

            if (!preg_match('#<h1[^>]*>(?P<title>[^<]*)</h1>#', $contest_page, $title_match)) {
                trigger_error("Failed to find contest title in " . $contest_url, E_USER_WARNING);
                continue;
            }
            $title = html_entity_decode($title_match['title']);

            if (!preg_match('#/contest/(?P<key>[^/]+)/?$#', $contest_url, $key_match)) {
                trigger_error("Failed to find contest key in " . $contest_url, E_USER_WARNING);
                continue;
            }
            $key = $key_match['key'];

            if (isset($seen[$key])) {
                trigger_error("Duplicate contest key found: $key in " . $contest_url, E_USER_WARNING);
                continue;
            }
            $seen[$key] = true;

            $contests[] = array(
                'start_time' => $variables['start-at'],
                'end_time' => $variables['end-at'],
                'title' => $title,
                'url' => $contest_url,
                'standings_url' => rtrim($contest_url, '/') . '/scoreboard',
                'key' => $key,
                'host' => $HOST,
                'rid' => $RID,
                'timezone' => $TIMEZONE,
                'info' => ['parse' => $variables],
            );
            $was_contest = true;

            if (!$parse_full_list && time() > $variables['end-at']) {
                break;
            }
        }
    }
?>
