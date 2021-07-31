<?php
    require_once dirname(__FILE__) . "/../../config.php";

    $add_full_list = isset($_GET['parse_full_list']);
    $urls = array("https://www.kaggle.com/competitions.json?");
    if (!$add_full_list) {
        $urls[] = "https://www.kaggle.com/competitions.json?sortBy=relevance&";
    }
    $added = array();
    foreach ($urls as $base_url) {
        for ($page = 1, $n_competition = -1; $page == 1 || ($n_competition && $add_full_list); ++$page) {
            $url = $base_url . "page=$page";
            $data = curlexec($url, NULL, array('json_output' => true));
            if (is_string($data) && strpos($data, '429 Too Many Requests') !== false) {
                trigger_error("Too many requests for parse kaggle.com", E_USER_WARNING);
                return;
            }
            if (!isset($data['fullCompetitionGroups'])) {
                trigger_error("Not found competition groups", E_USER_WARNING);
                return;
            }
            $list_of_competitions_list = array_merge(
                $data['fullCompetitionGroups'],
                array($data['pagedCompetitionGroup'])
            );

            $n_competition = 0;
            foreach ($list_of_competitions_list as $group_competitions) {
                $n_competition += count($group_competitions['competitions']);
                foreach ($group_competitions['competitions'] as $c) {
                    $ok = true;
                    foreach (array('competitionId', 'competitionTitle', 'competitionUrl') as $f) {
                        if (!isset($c[$f])) {
                            trigger_error("Not found ${f} field", E_USER_WARNING);
                            $ok = false;
                            break;
                        }
                    }
                    $id = $c['competitionId'];
                    if (!$ok || (isset($c['isPrivate']) && $c['isPrivate']) || isset($added[$id])) {
                        continue;
                    }
                    $added[$id] = true;

                    // echo $c['deadline'] . " " . $c['competitionTitle'] . " " . $id . "\n";

                    $contests[] = array(
                        'start_time' => $c['enabledDate'],
                        'end_time' => $c['deadline'],
                        'title' => $c['competitionTitle'],
                        'url' => url_merge($URL, $c['competitionUrl']),
                        'host' => $HOST,
                        'rid' => $RID,
                        'timezone' => $TIMEZONE,
                        'key' => $id
                    );
                }
            }
        }
    }

    if ($RID === -1) {
        echo "Total contests: " . count($added) . "\n";
    }
?>
