<?php
    require_once dirname(__FILE__) . "/../../config.php";

    if (!isset($URL)) $URL = "https://topcoder.com/community/events/";
    if (!isset($HOST)) $HOST = parse_url($URL, PHP_URL_HOST);
    if (!isset($RID)) $RID = -1;
    if (!isset($LANG)) $LANG = 'RU';
    if (!isset($TIMEZONE)) $TIMEZONE = 'America/New_York';
    if (!isset($contests)) $contests = array();

    $debug_ = $RID == -1;

    $_DATE_FORMAT = 'm.d.Y';

    $url_scheme_host = parse_url($URL, PHP_URL_SCHEME) . "://" . parse_url($URL, PHP_URL_HOST);

    foreach (array("past", "upcoming", "active") as $type) {
        $url = "https://api.topcoder.com/v2/data/marathon/challenges/?listType=" . $type;
        if ($debug_) {
            echo "url = $url\n";
        }
        $json = curlexec($url, null, array("json_output" => 1));
        if (isset($json["data"])) {
            foreach ($json["data"] as $c) {
                $ok = true;
                foreach (array("startDate", "endDate", "fullName", "roundId", "problemId") as $f) {
                    if (!isset($c[$f])) {
                        $ok = false;
                        break;
                    }
                }
                if ($ok) {
                    $url = $url_scheme_host . "/longcontest/?module=ViewProblemStatement&rd=${c['roundId']}&pm=${c['problemId']}";
                    $title = $c["fullName"];
                    $date = date($_DATE_FORMAT, strtotime($c["startDate"]));
                    $_contests[] = array(
                        "start_time" => $c["startDate"],
                        "end_time" => $c["endDate"],
                        "title" => $title,
                        "url" => $url
                    );
                }
            }
        }
    }

    $url = "https://api.topcoder.com/v2/challenges/active?challengeType=Code&technologies=Data+Science&type=develop";
    if ($debug_) {
        echo "url = $url\n";
    }
    $json = curlexec($url, NULL, array("json_output" => 1));
    if (isset($json["data"])) {
        foreach ($json["data"] as $c) {
            $ok = true;
            foreach (array("registrationStartDate", "submissionEndDate", "challengeName", "challengeId") as $f) {
                if (!isset($c[$f])) {
                    $ok = false;
                    break;
                }
            }
            if ($ok) {
                $url = $url_scheme_host . "/challenge-details/${c["challengeId"]}/";
                $title = $c["challengeName"];
                $date = date($_DATE_FORMAT, strtotime($c["registrationStartDate"]));
                $_contests[] = array(
                    "start_time" => $c["registrationStartDate"],
                    "end_time" => $c["submissionEndDate"],
                    "title" => $title,
                    "url" => $url
                );
            }
        }
    }

    $authorization = get_calendar_authorization();
    if ($authorization) {
        $calendar = "appirio.com_bhga3musitat85mhdrng9035jg@group.calendar.google.com";
        $url = "https://www.googleapis.com/calendar/v3/calendars/" . urlencode($calendar) . "/events?timeMin=" . urlencode(date("c", time() - 7 * 24 * 60 * 60));
        if ($debug_) {
            echo "url = $url\n";
        }
        $data = curlexec($url, NULL, array("http_header" => array("Authorization: $authorization"), "json_output" => 1));
        if (!isset($data["items"])) {
            print_r($data);
        } else {
            foreach ($data["items"] as $item)
            {
                if ($item["status"] != "confirmed" || !isset($item["summary"])) {
                    continue;
                }

                $title = $item["summary"];
                if (strpos($title, "Registration") !== false) {
                    continue;
                }
                $title = preg_replace("/ \(MM\)$/", "", $title);

                $url = $URL;
                foreach (array("description", "location") as $field) {
                    if (!isset($item[$field])) {
                        continue;
                    }
                    if (preg_match('#(?P<href>https?://[^\s"]*(?:MatchDetails|ViewProblemStatement)[^\s"]*)#', $item[$field], $match)) {
                        $url = $match["href"];
                        break;
                    }
                }

                $start = $item["start"][isset($item["start"]["dateTime"])? "dateTime" : "date"];
                $end = $item["end"][isset($item["end"]["dateTime"])? "dateTime" : "date"];
                $date = date($_DATE_FORMAT, strtotime($start));
                if (!isset($item["id"])) {
                    trigger_error("No set id for event $title", E_USER_WARNING);
                }
                $contest = array(
                    "start_time" => $start,
                    "end_time" => $end,
                    "title" => $title,
                    "url" => $url,
                    "_calendar" => true
                );
                $_contests[] = $contest;
            }
        }
    }

    usort($_contests, function ($a, $b) {
        return -(strlen($a["title"]) - strlen($b["title"]));
    });

    $_ = array();
    foreach ($_contests as $v) {
        $v['title'] = trim($v['title']);
        $v['title'] = preg_replace('/ {2,}/', ' ', $v['title']);
        $start_time = strtotime($v['start_time']);

        $ok = true;
        foreach ($_ as $c) {
            if (strpos($c['title'], $v['title']) !== false && strtotime($c['start_time']) == $start_time && $c['url'] == $v['url']) {
                $ok = false;
                break;
            }
        }

        if ($ok) {
            $_[] = $v;
        }
    }
    $_contests = $_;
    unset($_);

    $add_from_stats = isset($_GET['parse_full_list']);
    $iou_treshhold = 0.61803398875;

    $round_overview = array();
    foreach (array('https://www.topcoder.com/tc?module=MatchList', 'https://community.topcoder.com/longcontest/stats/?module=MatchList') as $base_url) {
        $nr = 200;
        $sr = 1;
        for (;;) {
            $url = $base_url . "&nr=$nr&sr=$sr";
            if ($debug_) {
                echo $url . "\n";
            }
            $page = curlexec($url);
            preg_match_all('#(?:<td[^>]*>(?:[^<]*<a[^>]*href="(?P<url>[^"]*/stat[^"]*rd=(?P<rd>[0-9]+)[^"]*)"[^>]*>(?P<title>[^<]*)</a>[^<]*|(?P<date>[0-9]+\.[0-9]+\.[0-9]+))</td>[^<]*){2}#', $page, $matches, PREG_SET_ORDER);
            foreach ($matches as $match) {
                $round_overview[$match['rd']] = array(
                    'url' => url_merge($base_url, htmlspecialchars_decode($match['url'])),
                    'title' => $match['title'],
                    'date' => $match['date']
                );
            }
            if (!$add_from_stats) {
                break;
            }
            if (!preg_match('#<a[^>]*href="(?P<url>[^"]*)"[^>]*>next#', $page, $match)) {
                break;
            }
            $sr += $nr;
        }
    }

    for ($iter = 0; $iter < 2; ++$iter) {
        foreach ($_contests as &$c) {
            $ret = preg_match('/&rd=(?P<rd>[0-9]+)/', $c['url'], $match);
            if ($ret != ($iter == 0)) {
                continue;
            }
            if ($ret) {
                $rd = $match['rd'];
                if (isset($round_overview[$rd])) {
                    $c['standings_url'] = $round_overview[$rd]['url'];
                    unset($round_overview[$rd]);
                }
            } else {
                if (!isset($c['_calendar'])) {
                    continue;
                }
                foreach (array(0, -1, 1) as $shift_day) {
                    $date = date('m.d.Y', strtotime($c['start_time']) + $shift_day * 24 * 60 * 60);
                    foreach ($round_overview as $k => $ro) {
                        if ($ro['date'] == $date) {
                            $w1 = explode(" ", $c["title"]);
                            $w2 = explode(" ", $ro["title"]);
                            $iou = count(array_intersect($w1, $w2)) / count(array_unique(array_merge($w1, $w2)));;
                            if ($iou > $iou_treshhold) {
                                $c['standings_url'] = $ro['url'];
                                unset($ro[$k]);
                                break;
                            }
                        }
                    }
                }
            }
        }
    }

    if ($add_from_stats) {
        foreach ($round_overview as $ro) {
            $ds = explode('.', $ro['date']);
            list($ds[0], $ds[1]) = array($ds[1], $ds[0]);
            $date = implode('.', $ds);
            $_contests[] = array(
                "start_time" => $date,
                "end_time" => $date,
                "title" => $ro['title'],
                "url" => $ro['url'],
                "standings_url" => $ro['url']
            );
        }
    }

    foreach ($_contests as $c) {
        unset($c['_calendar']);
        $c["host"] = $HOST;
        $c["rid"] = $RID;
        $c["timezone"] = "UTC";
        $contests[] = $c;
    }

    if ($RID === -1) {
        //print_r($_contests);
        echo "Total contests: " . count($_contests) . "\n";
    }
?>
