<?php
    $is_debug = true;
    class db
    {
        private string $host;
        private string $dbname;
        private int $port;
        private string $username;
        private string $password;
        private $link;
        private $result;

        function __construct()
        {
            $db_conf = parse_ini_file("/run/secrets/db_conf");
            $this->host = $db_conf['POSTGRES_HOST'];
            $this->dbname = $db_conf['POSTGRES_DB'];
            $this->port = $db_conf['POSTGRES_PORT'];
            $this->username = $db_conf['POSTGRES_USER'];
            $this->password = $db_conf['POSTGRES_PASSWORD'];

            $this->link = pg_connect("host={$this->host} port={$this->port} user={$this->username} password={$this->password} dbname={$this->dbname} options='--client_encoding=UTF8'");

            $this->link || die('Connection error');

            pg_client_encoding($this->link) == "UTF8" || die('Encoding is not UTF8');
            $this->query("SET TIME ZONE 'UTC';");
        }

        function query($sql, $ignore_error = false)
        {
            global $is_debug;
            $this->result = pg_query($this->link, $sql);

            if (!$this->result && $is_debug && !$ignore_error)
            {
                print "
                    <span style=\"color:#555555;font-size:12pt;font-family:'Arial';font-weight:bold;\">SQL query error:<br>&nbsp;&nbsp;&nbsp;Query: </span>
                    <span style=\"color:#000000;font-size:12pt;font-family:'Arial';\">" . $sql . "<br></span>
                ";
                exit(0);
            }
            return $this->result;
        }

        function getRow($sql)
        {
            return pg_fetch_assoc($this->query($sql));
        }

        function getValue($sql)
        {
            $arr = pg_fetch_array($this->query($sql));
            return $arr[0];
        }

        function getArray($sql)
        {
            $arr = array();
            $this->result = $this->query($sql);
            while ($this->result && $x = pg_fetch_assoc($this->result)) $arr[] = $x;
            return $arr;
        }

        function select($table, $fields = '*', $where = '1 = 1')
        {
            $sql = "select " . $fields . " from " . $table . " where $where";
            return $this->getArray($sql);
        }

        function escapeString($data)
        {
            if ($data === null) return null;
            return pg_escape_string($this->link, $data);
        }

        function escapeArray($a)
        {
            $res = array();
            foreach ($a as $k => $v) {
                $res[$k] = $this->escapeString($v);
            }
            return $res;
        }

        function getFirstRow($table, $fields, $where = false)
        {
            $sql = "select " . $fields . " from " . $table . "";
            if ($where) $sql  .= " where " . $where;
            return $this->getRow($sql);
        }

        function insert($table, $fields, $values)
        {
            $sql = "insert into " . $table . "(" . $fields . ") values (" . $values . ")";
            return $this->query($sql);
        }

        function delete($table, $where = false, $references = false)
        {
            $sql = "delete from " . $table . "";
            if ($where) {
                $sql .= " where " . $where;
                if ($references) {
                    foreach ($references as $ref_table => $ref_field) {
                        $delete_from_sql = "delete from " . $ref_table . " where " . $ref_field . " in (select id from " . $table . " where " . $where . ")";
                        $sql = $delete_from_sql . "; " . $sql;
                    }
                }
            }

            return $this->query($sql);
        }

        function update($table, $values, $where = '1 = 1')
        {
            $sql = "update " . $table . " set " . $values . " where " . $where;
            return $this->query($sql);
        }

        function affected_rows()
        {
            return pg_affected_rows($this->result);
        }

        function close()
        {
            if ($this->link) {
                pg_close($this->link);
            }
        }

        function __destruct()
        {
            $this->close();
        }
    }
    $db = new db();
?>
