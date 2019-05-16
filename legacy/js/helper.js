{literal}
    <script type="text/javascript">
        if (document.getElementsByClassName == undefined)
        {
           document.getElementsByClassName = function(cl)
           {
              var retnode = [];
              var myclass = new RegExp('\\b'+cl+'\\b');
              var elem = this.getElementsByTagName('*');
              for (var i = 0; i < elem.length; i++)
              {
                 var classes = elem[i].className;
                 if (myclass.test(classes))
                 {
                    retnode.push(elem[i]);
                 }
              }
              return retnode;
           }
        }

        function isInteger(x)
        {
            var y = parseInt(x);
            if (isNaN(y)) return false;
            return x == y && x.toString() == y.toString(); 
        }

        function implode(glue, pieces)
        {
            return ((pieces instanceof Array)? pieces.join(glue) : pieces);
        }

        function htmlspecialchars(s)
        {
            var obj = document.createElement("div");
            obj.innerText = obj.textContent = s;
            return obj.innerHTML;
        }

        String.prototype.format = function() {
          var args = arguments;
          return this.replace(/{(\d+)}/g, function(match, number) {
            return typeof args[number] != 'undefined'
              ? args[number]
              : match
            ;
          });
        };
    </script>
{/literal}
