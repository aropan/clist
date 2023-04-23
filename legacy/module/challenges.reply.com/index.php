<?php
    require_once dirname(__FILE__) . "/../../config.php";
    require_once dirname(__FILE__) . "/secret.php";

    $host = parse_url($URL, PHP_URL_SCHEME) . "://" . parse_url($URL, PHP_URL_HOST);

    $url = "https://challenges.reply.com/tamtamy/home.action";
    $page = curlexec($url);
    if (!preg_match('#<a[^>]*href="[^"]*Logout[^"]*"[^>]*>#', $page)) {
        $url = "https://challenges.reply.com/tamtamy/user/signIn.action";
        $data = array(
            "username" => $CHALLENGE_REPLY_EMAIL,
            "password" => $CHALLENGE_REPLY_PASSWORD,
            "remember" => true,
            "pageSourceType" => "MODAL",
        );
        $data = curlexec($url, $data, array("json_output" => true));
        if (!isset($data["message"])) {
            trigger_error("Invalid singin: $data", E_USER_WARNING);
            return;
        } else if (!isset($data["message"]) || strpos(strtolower($data["message"]), "success") === false) {
            trigger_error("Invalid singin: ${data['message']}", E_USER_WARNING);
            return;
        }
    }
    unset($CHALLENGE_REPLY_EMAIL);
    unset($CHALLENGE_REPLY_PASSWORD);

    $challenges = array();
    if (isset($_GET['parse_full_list'])) {
        $offset = 0;
        while (is_int($offset)) {
            $url = $host . "/tamtamy/api/challenge.json?searchBean.firstResult=$offset&searchBean.numberOfResult=100";
            $data = curlexec($url, NULL, array('json_output' => true));
            $offset = $data["paginationInfo"]["nextOffset"];
            foreach ($data["list"] as $c) {
                $challenges[] = $c;
            }
        }
    }

    $page = curlexec($URL);
    preg_match_all('#<a[^>]*href="(?P<url>[^"]*)"[^>]*class="[^"]*(code_challenge|hs_challenge|investment_challenge|ctf_challenge)[^"]*"[^>]*>#', $page, $matches);

    foreach ($matches['url'] as $url) {
        $url = url_merge($URL, $url);
        $page = curlexec($url);

        if (!preg_match('#<a[^>]*href="(?P<href>[^"]*/(detail|stats))"[^>]*class="[^"]*external-challenge[^"]*"[^>]*>#', $page, $match)) {
            continue;
        }
        $url = url_merge($url, $match['href']);

        $page = curlexec($url);
        $cid = NULL;
        if (preg_match('#CHALLENGE_DETAIL_ID\s*=\s*(?P<id>[0-9]+)#i', $page, $match)) {
            $cid = $match['id'];
        } else {
            preg_match_all("#data-tt-widget-params='(?P<json>[^']*)'#", $page, $matches);
            foreach ($matches['json'] as $json) {
                $data = json_decode($json, true);
                if (isset($data["params.challengeId"])) {
                    $cid = $data["params.challengeId"];
                    break;
                }
            }
            preg_match_all("#data-tt-widget-config='(?P<json>[^']*)'#", $page, $matches);
            foreach ($matches['json'] as $json) {
                $data = json_decode($json, true);
                if (isset($data["categoryId"]) && isset($data["id"])) {
                    $cid = $data["id"];
                    break;
                }
            }
        }
        if (empty($cid)) {
            continue;
        }

        $url = "$host/tamtamy/api/challenge/$cid.json?id=$cid";
        $challenge = curlexec($url, NULL, array("json_output" => true));
        $challenges[] = $challenge;
    };

    foreach ($challenges as $challenge) {
        $category = $challenge["category"]["id"];
        if ($category == "CREATIVE") {
            continue;
        }
        if ($category == "CODING_TEEN" && preg_match("#\btrain(?:ing)?\b#i", $challenge["title"])) {
            continue;
        }

        $title = str_replace("_", " ", $category);
        $title = ucwords(strtolower($title));
        $titles = explode(" - ", $challenge["title"]);
        $title .= ". " . $titles[0];

        $contests[] = array(
            'start_time' => $challenge["challengeStart"]["time"] / 1000,
            'end_time' => $challenge["challengeEnd"]["time"] / 1000,
            'title' => $title,
            'url' => "$host/tamtamy/challenge/${challenge['id']}/detail",
            'host' => $HOST,
            'key' => $challenge["id"],
            'rid' => $RID,
        );
    }

    if (DEBUG) {
        print_r($contests);
    }
?>
