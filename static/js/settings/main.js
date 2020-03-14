$(function() {
    $.fn.editable.defaults.mode = 'inline'
    $.fn.editable.defaults.url = 'change/'

    $.getJSON('/static/json/timezones.json', function(data) {
        var timezones = {}
        $.each(data, function(k, v) {
            timezones[v.name] = '{name} {repr}'.format(v);
        })

        $('#timezone').editable({
            type: 'select',
            source: timezones,
            showbuttons: false,
        }).on('shown', function(e, editable){
            editable.input.$input.select2({
                width: 250,
                placeholder: 'Select timezone',
                val: editable.input.$input.val(),

            });
            setTimeout(function() { editable.input.$input.select2('open'); }, 1);
        });
    })

    $('.value [type="checkbox"]:not([data-on])').each(function() {
        $(this).attr('data-on', 'Enabled')
        $(this).attr('data-off', 'Disabled')
    })
    $('.value [type="checkbox"]').each(function() {
        $(this).attr('checked', $(this).attr('data-value') == '1')
    }).bootstrapToggle({
        size: 'mini',
        width: 100,
        height: 20,
    }).change(function() {
        var $parent = $(this).parent().parent();
        if ($parent.find('.alert-danger').length == 0) {
            $parent.append('<div class="badge alert-danger" style="margin-left: 10px"></div>')
        }
        var $alert = $parent.find('.alert-danger')
        $alert.hide()
        $.ajax({
            type: 'POST',
            url: $.fn.editable.defaults.url,
            data: {
                pk: $.fn.editable.defaults.pk,
                name: $(this).attr('id'),
                value: $(this).prop('checked'),
            },
            success: function() {
                $alert.hide()
            },
            error: function (xhr, status, errorThrown) {
                $alert.text(xhr.responseText)
                $alert.show()
            },
        })
    })

    $('#time-format').editable({ type: 'text', })

    $('#add-to-calendar').editable({
        type: 'select',
        showbuttons: false,
        source: {
            'enable': 'Enable',
            'disable': 'Disable',
            'iCalendar': 'iCalendar',
            'Google Calendar': 'Google Calendar',
            'Outlook': 'Outlook',
            'Outlook Online': 'Outlook Online',
            'Yahoo! Calendar': 'Yahoo! Calendar',
        }
    }).on('shown', function(e, editable){
        editable.input.$input.select2({
            width: 250,
            placeholder: 'Select calendar type',
            val: editable.input.$input.val(),

        });
        setTimeout(function() { editable.input.$input.select2('open'); }, 1);
    });

    $('#view-mode').editable({
        type: 'select',
        showbuttons: false,
        source: {'list': 'List', 'calendar': 'Calendar'},
    })

    $('#email').editable({
        type: 'select',
        source: emails,
        showbuttons: false,
    })

    $('#country').editable({
        type: 'select',
        source: COUNTRIES,
        showbuttons: false,
    }).on('shown', function(e, editable){
        editable.input.$input.select2({
            width: 300,
            placeholder: 'Select country',
            val: editable.input.$input.val(),
            templateResult: function (data) {
                var $result = $('<span></span>')
                $result.text(data.text)
                if (data.id) {
                    var code = data.id.toLowerCase()
                    $result.prepend('<img class="flag flag-' + code + '"/>&nbsp;')
                }
                return $result
            },
            minimumInputLength: 0
        });
        setTimeout(function() { editable.input.$input.select2('open'); }, 1);
    })

    var Filter = function (options) {
        this.init('filter', options, Filter.defaults)
    }

    //inherit from Abstract input
    $.fn.editableutils.inherit(Filter, $.fn.editabletypes.abstractinput)

    $.extend(Filter.prototype, {
        render: function() {
            this.$input = this.$tpl.find('input')
            this.$resources = this.$tpl.find('#resources')
            this.$contest = this.$tpl.find('#contest')
            this.$categories = this.$tpl.find('#categories')

            this.$tpl.find("i[rel=tooltip]")
                .addClass('far fa-question-circle')
                .tooltip({
                    placement: 'right',
                    delay: {show: 500, hide: 100},
                })

            this.$resources.select2({
                data: RESOURCES,
                multiple: true,
                width: '100%',
                placeholder: 'Select resources',
            })

            this.$contest.select2({
                dropdownAutoWidth : true,
                width: '100%',
                theme: 'bootstrap',
                placeholder: 'Select contest',
                ajax: {
                    url: 'search/',
                    dataType: 'json',
                    delay: 314,
                    data: function (params) {
                        return {
                            query: 'notpast',
                            title: params.term,
                            page: params.page || 1
                        };
                    },
                    processResults: function (data, params) {
                        return {
                            results: data.items,
                            pagination: {
                                more: data.more
                            }
                        };
                    },
                    cache: true
                },
                minimumInputLength: 2,
            })

            this.$categories.select2({
                data: CATEGORIES,
                multiple: true,
                width: '100%',
                placeholder: 'Select categories',
            })


            this.$tpl.find('#select-all-resources').click(function() {
                $('#resources').val($.map(RESOURCES, function(r) { return r.id })).trigger('change')
                return false
            })

            this.$tpl.find('#deselect-all-resources').click(function() {
                $('#resources').val([]).trigger('change')
                return false
            })

            this.$tpl.find('#inverse-resources').click(function() {
                $('#resources').val(
                    $.grep(
                        $.map(RESOURCES, function(resource) {
                            return resource.id
                        }),
                        function(id) {
                            return $.inArray(id, $('#resources').val()) === -1
                        }
                    )
                ).trigger('change')
                return false
            })
        },

        value2html: function(value, element) {
            if(!value) {
                $(element).empty()
                return
            }
            var html = ''
            if (value.name) {
                html += value.name + ': '
            }
            html += value.to_show? 'show ' : 'hide '
            if (value.resources && value.resources.length) {
                html += value.resources.length + ' resource(s)'
            }
            if (value.contest) {
                if (value.resources.length) {
                    html += ','
                }
                if (value.contest__title) {
                    html += ' contest ' + value.contest__title;
                } else {
                    html += ' contest_id ' + value.contest
                }
            }
            if (value.duration && (value.duration.from || value.duration.to)) {
                html +=
                    ', duration'
                    + (value.duration.from? ' from ' + value.duration.from : '')
                    + (value.duration.to? ' to ' + value.duration.to : '')
            }
            if (value.regex) {
                html += ', with ' + (value.inverse_regex? 'inverse ' : '') + 'regex ' + value.regex
            }
            if (value.categories && value.categories.length) {
                html += ', for ' + value.categories.length + ' categories';
            }
            $(element).html(html)
        },

        html2value: function(html) { return null },

        value2str: function(value) {
            return JSON.stringify(value)
        },

        str2value: function(str) {
            return str
        },

        value2input: function(value) {
            if (!value) {
                return
            }
            this.$input.filter('[name="name"]').val(value.name)
            this.$input.filter('[name="id"]').val(value.id)
            if (value.duration) {
                this.$input.filter('[name="duration-from"]').val(value.duration.from)
                this.$input.filter('[name="duration-to"]').val(value.duration.to)
            }
            this.$input.filter('[name="regex"]').val(value.regex)
            this.$input.filter('[name="inverse-regex"]').attr('checked', value.inverse_regex)
            this.$input.filter('[name="to-show"]').attr('checked', value.to_show)
            this.$contest.select2('trigger', 'select', {data: {id: value.contest, text: value.contest__title}})
            this.$resources.val(value.resources).trigger('change')
            this.$categories.val(value.categories).trigger('change')
        },

        input2value: function() {
            contest_data = this.$contest.select2('data')
            result = {
                name: this.$input.filter('[name="name"]').val(),
                id: parseInt(this.$input.filter('[name="id"]').val()),
                duration: {
                    from: parseInt(this.$input.filter('[name="duration-from"]').val()),
                    to: parseInt(this.$input.filter('[name="duration-to"]').val()),
                },
                regex: this.$input.filter('[name="regex"]').val(),
                inverse_regex: this.$input.filter('[name="inverse-regex"]').prop('checked'),
                to_show: this.$input.filter('[name="to-show"]').prop('checked'),
                resources: $.map(this.$resources.val() || [], function (v) { return parseInt(v) }),
                contest: contest_data.length? contest_data[0].id : null,
                contest__title: contest_data.length? contest_data[0].text : null,
                categories: this.$categories.val() || [],
            }
            return result
        },

        activate: function () {
            this.$input[0].focus()
            this.$input.keypress(function (e) {
                if (e.which == 13) {
                    return false;
                }
            })
        },
    })

    Filter.defaults = $.extend({}, $.fn.editabletypes.abstractinput.defaults, {
        tpl: '\
<div> \
    <input type="hidden" name="id"> \
    <div class="filter-field"> \
        <div class="input-group input-group-sm"> \
            <span class="input-group-addon">Name</span> \
            <input name="name" maxlength="60" type="text" class="form-control"> \
        </div> \
        <div class="input-group input-group-sm"> \
            <span class="input-group-addon">To show</span> \
            <span class="input-group-addon"> \
                <input name="to-show" type="checkbox" rel="tooltip" title="To show"> \
            </span> \
        </div> \
        <div class="input-group input-group-sm select2-bootstrap-prepend select2-bootstrap-append"> \
            <select id="categories" class="form-control" name="categories[]"></select> \
        </div> \
    </div> \
    <div class="filter-field"> \
    </div> \
    <div class="filter-field"> \
        <div class="input-group input-group-sm"> \
            <span class="input-group-addon">Duration</span> \
            <span class="input-group-addon">from</span> \
            <input min="0" max="2139062143" type="number" class="form-control" name="duration-from"> \
            <span class="input-group-addon">to</span> \
            <input min="0" max="2139062143" type="number" class="form-control" name="duration-to"> \
            <span class="input-group-addon">minute(s)</span> \
        </div> \
    </div> \
    <div class="filter-field"> \
        <div class="input-group input-group-sm"> \
            <span class="input-group-addon">Regex</span> \
            <input name="regex" maxlength="1000" type="text" class="form-control"> \
        </div> \
        <div class="input-group input-group-sm"> \
            <span class="input-group-addon">Inverse regex</span> \
            <span class="input-group-addon"> \
                <input name="inverse-regex" type="checkbox" rel="tooltip" title="Inverse regex"> \
            </span> \
        </div> \
        <i rel="tooltip" title="Use `url:#regex#` to filter by regex by url"></i> \
    </div> \
    <div class="filter-field"> \
    </div> \
    <div class="filter-field"> \
        <div class="input-group input-group-sm"> \
            <span class="input-group-addon">Resources</span> \
            <span class="input-group-btn"> \
                <button id="select-all-resources" class="btn btn-default"><i class="fa fa-check"></i></button> \
                <button id="deselect-all-resources" class="btn btn-default"><i class="fa fa-times"></i></button> \
                <button id="inverse-resources" class="btn btn-default"><i class="fa fa-retweet"></i></button> \
            </span> \
        </div> \
        <div class="filter-field-resources"> \
            <select id="resources" class="form-control" name="resources[]"></select> \
        </div> \
    </div> \
    <div class="h5">OR</div> \
    <div class="filter-field"> \
        <div class="input-group input-group-sm"> \
            <span class="input-group-addon">Contest</span> \
            <select id="contest" class="form-control" name="contest"></select> \
        </div> \
        <i rel="tooltip" title="Use `Hide contest` option in preferences for a simple way to create contest filter"></i> \
    </div> \
</div> \
        ',
        inputclass: '',
    })

    $.fn.editabletypes.filter = Filter

    filterEditableOptions = {
        type: 'filter',
        showbuttons: 'bottom',
        error: function(data) {
            $('.editable-error-block')
                .addClass('alert')
                .addClass('alert-danger')
                .html(data.responseText).show()
        },
    }

    function filterEditableShown(e, editable) {
        $('[data-id="{0}"]'.format(editable.value.id)).addClass('hidden')
    }

    function filterEditableHidden(e, editable) {
        var $button = $('[data-id="{0}"]'.format($(this).data('editable').value.id))
        if ($(this).data('editable').value.resources.length == 0 && !$(this).data('editable').value.contest) {
            $button.click()
        } else {
            $button.removeClass('hidden')
        }
    }

    $('.filter').editable(filterEditableOptions)
    $('.filter').on('shown', filterEditableShown)
    $('.filter').on('hidden', filterEditableHidden)

    $('#add-filter-error').click(function() {
        $(this).addClass('hidden')
    })

    $('#add-filter').click(function() {
        $.ajax({
            type: 'POST',
            url: $.fn.editable.defaults.url,
            data: {
                pk: $.fn.editable.defaults.pk,
                name: 'add-filter',
            },
            success: function(data) {
                var $div = $('\
<div> \
    <a href="#" class="filter" data-name="filter" data-value=\'' + JSON.stringify(data) + '\'></a> \
    <a href="#" data-id="' + data.id + '" data-action="delete-filter" data-success="$div.remove();" class="action-filter btn btn-default btn-xs"> \
        <i class="far fa-trash-alt"></i> \
    </a> \
</div> \
                ')
                $div.find('.filter').editable(filterEditableOptions)
                $div.find('.filter').on('shown', filterEditableShown)
                $div.find('.filter').on('hidden', filterEditableHidden)

                $div.find('.action-filter').click(sentAction)
                $div.appendTo('#filters')
                $div.find('.filter').click()
            },
            error: function(data) {
                $('#add-filter-error').removeClass('hidden').html(data.responseText)
            },
        })
        return false
    })

    function sentAction() {
        var $this = $(this)
        var $div = $this.parent()
        bootbox.confirm({
            size: 'small',
            message: $div.text() +
                "<br/><br/>" +
                "<b>" + $this.attr('data-action').replace('-', ' ').toTitleCase() + "?</b>",
            callback: function(result) {
                if (result) {
                    $.ajax({
                        type: 'POST',
                        url: $.fn.editable.defaults.url,
                        data: {
                            pk: $.fn.editable.defaults.pk,
                            name: $this.attr('data-action'),
                            id: $this.data("id"),
                        },
                        success: function(data) {
                            eval($this.attr('data-success'))
                        },
                        error: function(data) {
                            $.notify("{status} {statusText}: {responseText}".format(data), "error");
                        },
                    })
                }
            }
        })
        return false
    }
    $('.action-notification').click(sentAction)
    $('.action-filter').click(sentAction)

    $("i[rel=tooltip]")
        .addClass('far fa-question-circle')
        .tooltip({
            placement: 'right',
            delay: {show: 500, hide: 100},
        })

    $('#first-name').editable({ type: 'text', })
    $('#last-name').editable({ type: 'text', })
    $('#first-name-native').editable({ type: 'text', })
    $('#last-name-native').editable({ type: 'text', })

    var $resource = $('select#add-account-resource')
    $resource.select2({
        width: '50%',
        allowClear: true,
        placeholder: 'Search resource by regex',
        ajax: {
            url: 'search/',
            dataType: 'json',
            delay: 314,
            data: function (params) {
                return {
                    query: 'resources-for-add-account',
                    regex: params.term,
                    page: params.page || 1
                };
            },
            processResults: function (data, params) {
                return {
                    results: data.items,
                    pagination: {
                        more: data.more
                    }
                };
            },
        },
        minimumInputLength: 0
    })

    $errorAccountTab = $('#error-account-tab')
    var $listAccount = $('#list-accounts')
    function addAccount(index, element) {
        var h4 = $('<h4>')
            .append($('<a>', {class: 'delete-account btn btn-default btn-xs'}).append($('<i>', {class: 'far fa-trash-alt'})))
            .append($('<span>', {text: ' '}))
            .append($('<a>', {class: 'small', href: 'http://' + element.resource, text: element.resource}))
            .append($('<span>', {text: ' '}))
            .append($('<span>', {text: element.account + (element.name && element.account.indexOf(element.name) == -1? ' | ' + element.name : '')}))

        var $block = $('<div class="account">').append(h4)

        $block.find('.delete-account').click(function() {
            var $this = $(this)
            var $account = $this.closest('.account')
            bootbox.confirm({
                size: 'small',
                message: $account.text() + "<br/><br/><b>Delete Account?</b>",
                callback: function(result) {
                    if (result) {
                        $.ajax({
                            type: 'POST',
                            url: $.fn.editable.defaults.url,
                            data: {
                                pk: $.fn.editable.defaults.pk,
                                name: 'delete-account',
                                resource: element.resource,
                                value: element.account,
                            },
                            success: function(data) {
                                $account.remove()
                            },
                            error: function(data) {
                                $errorAccountTab.show().html(data.responseText)
                                setTimeout(function() { $errorAccountTab.hide(500) }, 3000)
                            },
                        })
                    }
                }
            })
        })

        $listAccount.prepend($block)
    }
    $.each(ACCOUNTS, addAccount)

    var $search = $('#add-account-search')
    $search.select2({
        width: '50%',
        allowClear: true,
        placeholder: 'Search handle by regex',
        ajax: {
            url: 'search/',
            dataType: 'json',
            delay: 314,
            data: function (params) {
                return {
                    query: 'accounts-for-add-account',
                    user: params.term,
                    resource: $resource.val(),
                    page: params.page || 1
                };
            },
            processResults: function (data, params) {
                return {
                    results: data.items,
                    pagination: {
                        more: data.more
                    }
                };
            },
        },
        minimumInputLength: 0
    }).on('select2:select', function (e) {
        var account = $search.select2('data')[0]
        if (account.resource) {
            $resource.append('<option selected="selected" value="' + account.resource.id + '">' + account.resource.text+ '</option>')
        }
    });

    var $button = $('#add-account')

    $button.click(function() {
        $.ajax({
            type: 'POST',
            url: $.fn.editable.defaults.url,
            data: {
                pk: $.fn.editable.defaults.pk,
                name: 'add-account',
                resource: $resource.val(),
                value: $search.val(),
            },
            success: function(data) {
                addAccount(-1, data)
                $resource.val(null).trigger('change');
                $search.val(null).trigger('change');

            },
            error: function(data) {
                $errorAccountTab.show().html(data.responseText)
                setTimeout(function() { $errorAccountTab.hide(500) }, 3000)
            },
        })
    })

    var $search_org = $('#organization-search')
    $search_org.select2({
        width: '50%',
        ajax: {
            url: 'search/',
            dataType: 'json',
            delay: 314,
            data: function (params) {
                return {
                    query: 'organization',
                    name: params.term,
                    page: params.page || 1
                };
            },
            processResults: function (data, params) {
                return {
                    results: data.items,
                    pagination: {
                        more: data.more
                    }
                };
            },
            cache: true
        },
        minimumInputLength: 0
    })


})
