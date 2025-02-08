$(function() {
    $.fn.editable.defaults.mode = 'inline'
    $.fn.editable.defaults.url = change_url
    $.fn.editable.defaults.pk = coder_pk

    $('#theme').editable({
        type: 'select',
        source: '/settings/search/?query=themes',
        showbuttons: false,
        display: function(value, sourceData, response) {
            if (response == 'accepted') {
                window.location.replace(PREFERENCES_URL);
            }
            if (value) {
                $(this).html(value.charAt(0).toUpperCase() + value.slice(1));
            }
        },
        onblur: 'ignore',
    }).on('shown', function(e, editable){
        editable.input.$input.select2({
            width: 250,
            placeholder: 'Select theme',
            val: editable.input.$input.val(),
        }).change(function() {
            setTimeout(function() { editable.input.$input.select2('close'); }, 1);
        })
        setTimeout(function() { editable.input.$input.select2('open'); }, 1);
    })

    $('#highlight').editable({
        type: 'select',
        source: '/settings/search/?query=highlights',
        showbuttons: false,
        display: function(value, sourceData, response) {
            if (response == 'accepted') {
                window.location.replace(PREFERENCES_URL);
            }
            if (value) {
                $(this).html(value.charAt(0).toUpperCase() + value.slice(1));
            }
        },
        onblur: 'ignore',
    }).on('shown', function(e, editable){
        editable.input.$input.select2({
            width: 250,
            placeholder: 'Select highlight',
            val: editable.input.$input.val(),
        }).change(function() {
            setTimeout(function() { editable.input.$input.select2('close'); }, 1);
        })
        setTimeout(function() { editable.input.$input.select2('open'); }, 1);
    })

    $('#timezone').editable({
        type: 'select',
        source: '/settings/search/?query=timezones',
        showbuttons: false,
        onblur: 'ignore',
    }).on('shown', function(e, editable){
        editable.input.$input.select2({
            width: 250,
            placeholder: 'Select timezone',
            val: editable.input.$input.val(),

        });
        setTimeout(function() { editable.input.$input.select2('open'); }, 1);
    });

    $('#preferences-tab .value [type="checkbox"]:not([data-on])').each(function() {
        $(this).attr('data-on', 'Enabled')
        $(this).attr('data-off', 'Disabled')
    })
    $('#preferences-tab .value [type="checkbox"]').each(function() {
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
        source: ACE_CALENDARS,
        onblur: 'ignore',
    }).on('shown', function(e, editable){
        editable.input.$input.select2({
            width: 250,
            placeholder: 'Select calendar type',
            val: editable.input.$input.val(),

        });
        setTimeout(function() { editable.input.$input.select2('open'); }, 1);
    });

    $('#share-to-category').editable({
        type: 'select',
        showbuttons: false,
        source: SHARE_TO_CATEGORY,
        onblur: 'ignore',
    }).on('shown', function(e, editable){
        editable.input.$input.select2({
            width: 250,
            placeholder: 'Select category',
            val: editable.input.$input.val(),
        });
        setTimeout(function() { editable.input.$input.select2('open'); }, 1);
    });

    $('#past-action-in-calendar').editable({
        type: 'select',
        showbuttons: false,
        source: PAST_CALENDAR_ACTIONS,
        onblur: 'ignore',
    }).on('shown', function(e, editable){
        editable.input.$input.select2({
            width: 250,
            placeholder: 'Select action',
            val: editable.input.$input.val(),
        });
        setTimeout(function() { editable.input.$input.select2('open'); }, 1);
    });

    event_limit_source = ['true', 'false']
    for (i = 1; i < 20; ++i) { event_limit_source.push(i.toString()) }
    $('#event-limit-calendar').editable({
        type: 'select',
        showbuttons: false,
        source: event_limit_source,
        onblur: 'ignore',
    }).on('shown', function(e, editable){
        editable.input.$input.select2({
            width: 250,
            placeholder: 'Select event limit',
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
        onblur: 'ignore',
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
                    $result.prepend('<div class="flag flag-' + code + '"></div>')
                }
                return $result
            },
            minimumInputLength: 0
        }).on('select2:select', function (e) {
            var country = e.params.data.id
            $('.custom-countries').addClass('hidden')
            $('.custom-countries[data-country="' + country + '"]').removeClass('hidden')
        })

        setTimeout(function() { editable.input.$input.select2('open'); }, 1)
    })


    $('.custom-countries').click(function() {
        var a = $(this)
        var country = a.data('country')
        var value = a.data('value')
        $('.custom-countries[data-country="' + country + '"]').blur()

        $('#custom_countries_loading').removeClass('hidden')

        $.ajax({
            type: 'POST',
            url: $.fn.editable.defaults.url,
            data: {
                pk: $.fn.editable.defaults.pk,
                name: 'custom-countries',
                country: country,
                value: value,
            },
            success: function(data) {
                $('.custom-countries[data-country="' + country + '"]').removeClass('active')
                $('.custom-countries[data-value="' + value + '"]').addClass('active')
                $('#custom_countries_loading').addClass('hidden')
            },
            error: function(data) {
                notify(data.responseText, 'error')
                $('#custom_countries_loading').addClass('hidden')
            },
        })
        return false
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
            this.$party = this.$tpl.find('#party')
            this.$categories = this.$tpl.find('#categories')
            this.$week_days = this.$tpl.find('#week_days')

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
                theme: 'bootstrap',
            })

            this.$contest.select2({
                dropdownAutoWidth : true,
                width: '100%',
                placeholder: 'Select contest',
                theme: 'bootstrap',
                allowClear: true,
                ajax: select2_ajax_conf('notpast', 'regex'),
                minimumInputLength: 2,
            })

            this.$party.select2({
                dropdownAutoWidth : true,
                width: '100%',
                placeholder: 'Select party',
                theme: 'bootstrap',
                allowClear: true,
                ajax: select2_ajax_conf('party', 'name'),
                minimumInputLength: 2,
            })

            this.$categories.select2({
                data: CATEGORIES,
                multiple: true,
                width: '100%',
                placeholder: 'Select categories',
                theme: 'bootstrap',
                allowClear: true,
            })

            this.$week_days.select2({
                data: WEEK_DAYS,
                multiple: true,
                width: '100%',
                placeholder: 'Select days of week',
                theme: 'bootstrap',
                allowClear: true,
                dropdownAutoWidth: true,
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

            this.$tpl.find('#inverse-week-days').click(function() {
                $('#week_days').val(
                    $.grep(
                        $.map(WEEK_DAYS, function(week_day) {
                            return week_day.id
                        }),
                        function(id) {
                            return $.inArray(id, $('#week_days').val()) === -1
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
                if (html.slice(-1) != ' ') {
                    html += ','
                }
                if (value.contest__title) {
                    html += ' contest ' + value.contest__title;
                } else {
                    html += ' contest_id ' + value.contest
                }
            }
            if (value.party) {
                if (html.slice(-1) != ' ') {
                    html += ','
                }
                if (value.party__name) {
                    html += ' party ' + value.party__name;
                } else {
                    html += ' party_id ' + value.party
                }
            }
            if (value.duration && (value.duration.from || value.duration.to)) {
                html +=
                    ', duration'
                    + (value.duration.from? ' from ' + value.duration.from : '')
                    + (value.duration.to? ' to ' + value.duration.to : '')
            }
            if (value.start_time && (value.start_time.from || value.start_time.to)) {
                html +=
                    ', start time'
                    + (value.start_time.from? ' from ' + value.start_time.from : '')
                    + (value.start_time.to? ' to ' + value.start_time.to : '')
            }
            if (value.regex) {
                html += ', with ' + (value.inverse_regex? 'inverse ' : '') + 'regex ' + value.regex
            }
            if (value.host) {
                html += ', with host ' + value.host
            }
            if (value.week_days && value.week_days.length) {
                html += ', ' + value.week_days.length + ' week day(s)'
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
            if (value.start_time) {
                this.$input.filter('[name="start-time-from"]').val(value.start_time.from)
                this.$input.filter('[name="start-time-to"]').val(value.start_time.to)
            }
            this.$input.filter('[name="regex"]').val(value.regex)
            this.$input.filter('[name="inverse-regex"]').attr('checked', value.inverse_regex)
            this.$input.filter('[name="host"]').val(value.host)
            this.$input.filter('[name="to-show"]').attr('checked', value.to_show)
            this.$contest.select2('trigger', 'select', {data: {id: value.contest, text: value.contest__title}})
            this.$party.select2('trigger', 'select', {data: {id: value.party, text: value.party__name}})
            this.$resources.val(value.resources).trigger('change')
            this.$categories.val(value.categories).trigger('change')
            this.$week_days.val(value.week_days).trigger('change')
        },

        input2value: function() {
            contest_data = this.$contest.select2('data')
            party_data = this.$party.select2('data')
            result = {
                name: this.$input.filter('[name="name"]').val(),
                id: parseInt(this.$input.filter('[name="id"]').val()),
                duration: {
                    from: parseInt(this.$input.filter('[name="duration-from"]').val()),
                    to: parseInt(this.$input.filter('[name="duration-to"]').val()),
                },
                start_time: {
                    from: parseFloat(this.$input.filter('[name="start-time-from"]').val()),
                    to: parseFloat(this.$input.filter('[name="start-time-to"]').val()),
                },
                regex: this.$input.filter('[name="regex"]').val(),
                inverse_regex: this.$input.filter('[name="inverse-regex"]').prop('checked'),
                host: this.$input.filter('[name="host"]').val(),
                to_show: this.$input.filter('[name="to-show"]').prop('checked'),
                resources: $.map(this.$resources.val() || [], function (v) { return parseInt(v) }),
                contest: contest_data.length? contest_data[0].id : null,
                contest__title: contest_data.length? contest_data[0].text : null,
                party: party_data.length? party_data[0].id : null,
                party__name: party_data.length? party_data[0].text : null,
                categories: this.$categories.val() || [],
                week_days: this.$week_days.val() || [],
            }
            return result
        },

        activate: function () {
            this.$input.keypress(function (e) {
                if (e.which == 13) {
                    return false;
                }
            })
            this.$input.filter('[name="name"]').focus()
        },
    })

    Filter.defaults = $.extend({}, $.fn.editabletypes.abstractinput.defaults, {
        tpl: '\
<div> \
    <input type="hidden" name="id"> \
    <div class="filter-field"> \
        <div class="input-group input-group-md"> \
            <span class="input-group-addon">Name</span> \
            <input name="name" maxlength="60" type="text" class="form-control"> \
        </div> \
    </div> \
    <div class="filter-field"> \
        <div class="input-group input-group-md"> \
            <span class="input-group-addon">Show / Hide</span> \
            <span class="input-group-addon"> \
                <input name="to-show" type="checkbox" rel="tooltip" title="select to show"> \
            </span> \
        </div> \
    </div> \
    <div class="filter-field"> \
        <div class="input-group input-group-md"> \
            <span class="input-group-addon">Categories</span> \
            <select id="categories" class="form-control" name="categories[]"></select> \
        </div> \
    </div> \
    <div class="filter-field"> \
        <div class="input-group input-group-md"> \
            <span class="input-group-addon">Duration</span> \
            <span class="input-group-addon">from</span> \
            <input min="0" max="2139062143" type="number" class="form-control" name="duration-from"> \
            <span class="input-group-addon">to</span> \
            <input min="0" max="2139062143" type="number" class="form-control" name="duration-to"> \
            <span class="input-group-addon">minute(s)</span> \
        </div> \
    </div> \
    <div class="filter-field"> \
        <div class="input-group input-group-md"> \
            <span class="input-group-addon">Start time</span> \
            <span class="input-group-addon">from</span> \
            <input min="0" max="24" type="number" step="0.1" class="form-control" name="start-time-from"> \
            <span class="input-group-addon">to</span> \
            <input min="0" max="24" type="number" step="0.1" class="form-control" name="start-time-to"> \
            <span class="input-group-addon">hour(s)</span> \
        </div> \
        <i rel="tooltip" title="24-hour clock format in your time zone"></i> \
    </div> \
    <div class="filter-field"> \
        <div class="input-group input-group-md"> \
            <span class="input-group-addon">Week days</span> \
            <select id="week_days" class="form-control" name="week_days[]"></select> \
            <span class="input-group-btn"> \
                <button id="inverse-week-days" class="btn btn-default" title="inverse"><i class="fas fa-sync-alt"></i></button> \
            </span> \
        </div> \
        <i rel="tooltip" title="Start day of the week in your time zone"></i> \
    </div> \
    <div class="filter-field"> \
        <div class="input-group input-group-md"> \
            <span class="input-group-addon">Regex</span> \
            <input name="regex" maxlength="1000" type="text" class="form-control"> \
        </div> \
        <div class="input-group input-group-md"> \
            <span class="input-group-addon">Inverse regex</span> \
            <span class="input-group-addon"> \
                <input name="inverse-regex" type="checkbox" rel="tooltip" title="Inverse regex"> \
            </span> \
        </div> \
        <i rel="tooltip" title="Use `url:#regex#` to filter by regex by url"></i> \
    </div> \
    <div class="filter-field"> \
        <div class="input-group input-group-md"> \
            <span class="input-group-addon">Host</span> \
            <input name="host" maxlength="1000" type="text" class="form-control"> \
        </div> \
    </div> \
    <div class="filter-field"> \
        <div class="input-group input-group-md"> \
            <span class="input-group-addon">Resources</span> \
            <select id="resources" class="form-control" name="resources[]"></select> \
            <span class="input-group-btn"> \
                <button id="select-all-resources" class="btn btn-default"><i class="fa fa-check"></i></button> \
                <button id="deselect-all-resources" class="btn btn-default"><i class="fa fa-times"></i></button> \
                <button id="inverse-resources" class="btn btn-default" title="inverse"><i class="fas fa-sync-alt"></i></button> \
            </span> \
        </div> \
    </div> \
    <div class="h5">OR</div> \
    <div class="filter-field"> \
        <div class="input-group input-group-md"> \
            <span class="input-group-addon">Contest</span> \
            <select id="contest" class="form-control" name="contest"></select> \
        </div> \
        <i rel="tooltip" title="Use `Hide contest` option in preferences for a simple way to create contest filter"></i> \
    </div> \
    <div class="h5">OR</div> \
    <div class="filter-field"> \
        <div class="input-group input-group-md"> \
            <span class="input-group-addon">Party</span> \
            <select id="party" class="form-control" name="party"></select> \
        </div> \
    </div> \
</div> \
        ',
        inputclass: '',
    })

    $.fn.editabletypes.filter = Filter

    filterEditableOptions = {
        type: 'filter',
        showbuttons: 'bottom',
        onblur: 'ignore',
        error: function(data) {
            $('.editable-error-block')
                .addClass('alert')
                .addClass('alert-danger')
                .html(data.responseText).show()
        },
    }

    function filterEditableShown(e, editable) {
        var $button = $('[data-id="{0}"]'.format(editable.value.id))
        $button.addClass('hidden')

        var shown_filter = $button.parent().find('.shown-filter')
        if (shown_filter.length) {
            toggle_show_filter($button)
        }

        $close_button = $button.parent().find('.editable-cancel')
        $close_button.attr('disabled', 'disabled')
        $('#filters .editable-cancel:not([disabled])').click()
        $close_button.removeAttr('disabled')
    }

    function filterEditableHidden(e, editable) {
        var $button = $('[data-id="{0}"]'.format($(this).data('editable').value.id))
        if ($(this).data('editable').value.resources.length == 0
            && !$(this).data('editable').value.contest
            && !$(this).data('editable').value.party
        ) {
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
    <a href="#" data-id="' + data.id + '" data-action="delete-filter" data-success="$element.remove();" class="action-filter btn btn-default btn-xs"> \
        <i class="far fa-trash-alt"></i> \
    </a> \
</div> \
                ')
                $div.find('.filter').editable(filterEditableOptions)
                $div.find('.filter').on('shown', filterEditableShown)
                $div.find('.filter').on('hidden', filterEditableHidden)

                $div.find('.action-filter').click(sentAction)
                $div.prependTo('#filters')
                $div.find('.filter').click()
            },
            error: function(data) {
                $('#add-filter-error').removeClass('hidden').html(data.responseText)
            },
        })
        return false
    })

    function process_list() {
        name = $(this).attr('data-name')
        value = $(this).attr('data-value') || ''
        access_level = $(this).attr('data-access-level') || ACCESS_LEVELS[0]['id']
        shared_with = JSON.parse($(this).attr('data-shared-with') || "[]")
        id = $(this).attr('data-id') || ''
        custom_names = $(this).attr('data-custom-names') == 'true'

        const access_level_select_options = ACCESS_LEVELS.map(level => `
            <option value="${level.id}" ${level.id === access_level ? 'selected' : ''}>${level.text}</option>
        `).join('')

        const shared_with_select_options = shared_with.map(user => `
            <option value="${user.id}" selected>${user.username}</option>
        `).join('')

        var dialog = bootbox.dialog({
            title: id? 'Editing list' : 'Creating list',
            message: `
                <form id="list-form">
                    <div class="form-group">
                        <label class="control-label" for="textInput">Name</label>
                        <div><input id="list-name" type="text" class="form-control" value="` + escape_html(value) + `" required></div>
                        <small class="form-text text-muted">Required field</small>
                    </div>

                    <div class="form-group">
                        <label class="control-label" for="selectInput">Access level</label>
                        <div><select id="list-access-level" class="form-control">` + access_level_select_options + `</select></div>
                    </div>

                    <div class="form-group">
                        <label class="control-label" for="selectInput">Shared with:</label>
                        <div><select id="list-shared-with" class="form-control" multiple>` + shared_with_select_options + `</select></div>
                        <small class="form-text text-muted">Used only with restricted access level</small>
                    </div>

                    <div class="form-group">
                      <label class="control-label">Custom names</label>
                      <input id="list-custom-names" class="hidden" type="checkbox" data-toggle="toggle" data-on="On" data-off="Off" data-onstyle="default" data-offstyle="default" data-size="normal" name="custom_names"` + (custom_names? " checked" : "") + `>
                    </div>
                </form>
                <script>
                    coders_select('#list-shared-with')
                    $('#list-access-level').on('change', function() {
                        $('#list-shared-with').closest('.form-group').toggle($(this).val() == 'restricted')
                    }).change()
                </script>
            `,
            buttons: {
                cancel: {
                    label: "Cancel",
                    className: "btn-default",
                },
                success: {
                    label: "OK",
                    className: "btn-primary change-list-ok",
                    callback: function () {
                        var form = document.getElementById('list-form')
                        if (!form.checkValidity()) {
                            form.reportValidity()
                            return false
                        }

                        var btn = dialog.find('.change-list-ok')
                        var original_html = btn.html()
                        btn.html('<i class="fas fa-circle-notch fa-spin"></i>')

                        $.ajax({
                            type: 'POST',
                            url: $.fn.editable.defaults.url,
                            data: {
                                pk: $.fn.editable.defaults.pk,
                                name: name,
                                value: $('#list-name').val(),
                                access_level: $('#list-access-level').val(),
                                shared_with: $('#list-shared-with').val(),
                                custom_names: $('#list-custom-names').prop('checked'),
                                id: id,
                            },
                            success: function(data) {
                                window.location.replace(LISTS_URL)
                            },
                            error: function(response) {
                                btn.html(original_html)
                                log_ajax_error(response)
                            },
                        })
                        return false
                    }
                }
            }
        }).on('shown.bs.modal', function() {
            var $custom_names = $('#list-custom-names')
            $custom_names.bootstrapToggle()
        })
    }

    $('#add-list').click(process_list)
    $('.edit-list').click(process_list)

    function process_calendar() {
        name = $(this).attr('data-name')
        id = $(this).attr('data-id') || ''
        value = $(this).attr('data-value') || ''
        category = $(this).attr('data-category') || ''
        resources = JSON.parse($(this).attr('data-resources') || "[]")
        descriptions = JSON.parse($(this).attr('data-descriptions') || "[]")

        var category_select = '<option></option>'
        CATEGORIES.forEach(el => { category_select += '<option value="' + escape_html(el['id']) + '"' + (category == el['id']? ' selected' : '') + '>' + escape_html(el['text']) + '</option>' })

        var resources_select = ''
        RESOURCES.forEach(el => { resources_select += '<option value="' + escape_html(el['id']) + '"' + ($.inArray(parseInt(el['id']), resources) !== -1? ' selected' : '') + '>' + escape_html(el['text']) + '</option>' })

        var descriptions_select_after = ''
        var descriptions_options = {}
        EVENT_DESCRIPTIONS.forEach(el => {
            var has = $.inArray(parseInt(el['id']), descriptions) !== -1
            var option = '<option value="' + escape_html(el['id']) + '"' + (has? ' selected' : '') + '>' + escape_html(el['text']) + '</option>'
            if (has) {
                descriptions_options[el['id']] = option
            } else {
                descriptions_select_after += option
            }
        })
        var descriptions_select_before = ''
        descriptions.forEach(id => { descriptions_select_before += descriptions_options[id] })
        var descriptions_select = descriptions_select_before + descriptions_select_after

        var form = $(`
          <form>
            <div class="form-group">
              <label class="control-label">Calendar name</label>
              <input class="form-control" placeholder="Name" autocomplete="off" name="name" value="` + value + `" required maxlength="64">
              <small class="form-text text-muted">Required field</small>
            </div>
            <div class="form-group">
              <label class="control-label">Filter</label>
              <select class="form-control" name="category">` + category_select + `</select>
              <small class="form-text text-muted">Used to filter contests. Configure <a href="` + FILTERS_URL + `" target="_blank">here</a>. Optional field</small>
            </div>
            <div class="form-group">
              <label class="control-label">Resources <a class="inverse-resources btn btn-default btn-xs" title="inverse"><i class="fas fa-sync-alt"></i></a></label>
              <select class="form-control" name="resources" multiple>` + resources_select + `</select>
              <small class="form-text text-muted">Additional filter for resource. Full list <a href="` + RESOURCES_URL + `" target="_blank">here</a>. Optional field</small>
            </div>
            <div class="form-group">
              <label class="control-label">Event description</label>
              <select class="form-control" name="descriptions" multiple>` + descriptions_select + `</select>
              <small class="form-text text-muted">Order sensitive. Optional field</small>
            </div>
          </form>
        `);
        form.find('select').select2({width: '100%'})
        var $select_descriptions = $(form.find('select[name=descriptions]')[0])
        $select_descriptions.select2({
            width: '100%',
            sorter: function(items) {
                var sorted_items = []
                items.forEach((item, idx) => {
                    sorted_items[item.sorter_index ?? idx] = item
                })
                ret = []
                ret.push(...sorted_items.filter(i => i.selected ))
                ret.push(...sorted_items.filter(i => !i.selected ))
                var new_order = {}
                ret.forEach((item, idx) => {
                    item.sorter_index = idx
                    new_order[item.id] = idx
                })
                var new_options = []
                $options = $select_descriptions.children('option').detach()
                $options.each((idx, option) => {
                    var $option = $(option)
                    var id = $option.attr('value')
                    new_options[new_order[id]] = $option
                })
                $select_descriptions.append(new_options)
                $select_descriptions.trigger('change.select2')
                return ret
            },
        })

        form.find('.inverse-resources').click(() => {
            var resources = form.find('select[name=resources]')
            resources.val(
                $.grep(
                    $.map(RESOURCES, function(resource) { return resource.id }),
                    function(id) { return $.inArray(id, resources.val()) === -1 }
                )
            ).trigger('change')
            return false
        })

        bootbox.confirm(form, function(result) {
            if (!result) {
                return;
            }
            var input = form.find('input[name=name]')
            if (!input[0].checkValidity()) {
                input.closest('.form-group').addClass('has-error')
                return false;
            }
            value = form.find('input[name=name]').val()
            category = form.find('select[name=category]').val()
            resources = form.find('select[name=resources]').val()
            descriptions = form.find('select[name=descriptions]').val()
            $.ajax({
                type: 'POST',
                url: $.fn.editable.defaults.url,
                data: {
                    pk: $.fn.editable.defaults.pk,
                    name: name,
                    value: value,
                    category: category,
                    resources: resources,
                    descriptions: descriptions,
                    id: id,
                },
                success: function(data) {
                    window.location.replace(CALENDARS_URL)
                },
                error: function(response) {
                    log_ajax_error(response)
                },
            })
        })
        $('.bootbox.modal').removeAttr('tabindex')
    }

    function copy_calendar_url() {
        copyTextToClipboard($(this).attr('data-url'))
        var help = $(this).parent().find('.copy-url-help')
        help.removeClass('hidden')
        help.fadeIn('fast')
        setTimeout(() => help.fadeOut('slow'), 1000)
    }

    $('#add-calendar').click(process_calendar)
    $('.edit-calendar').click(process_calendar)
    $('.copy-calendar-url').click(copy_calendar_url)

    function process_subscription() {
        name = $(this).attr('data-name')
        data = $(this).data('form')

        var form = $(`
          <h3>` + (data? 'Edit' : 'Create') + ` subscription</h3>
          <form id="subscription_form">
            <div class="form-group">
              <label class="control-label">Resource</label>
              <select class="form-control" name="resource"></select>
            </div>
            <div class="form-group">
              <label class="control-label">Contest</label>
              <select class="form-control" name="contest"></select>
            </div>
            <div class="form-group">
              <label class="control-label">First accepted</label>
              <input type="checkbox" data-toggle="toggle" data-on="On" data-off="Off" data-onstyle="default" data-offstyle="default" data-size="normal" name="with_first_accepted">
            </div>
            <div class="form-group">
              <label class="control-label">Top n</label>
              <input type="number" class="form-control" name="top_n" min="1" max="` + SUBSCRIPTION_TOP_N_LIMIT + `">
            </div>
            <div class="form-group">
              <label class="control-label">Accounts <a href="` + ACCOUNTS_URL + `" target="_blank">` + EXTRA_URL_ICON + `</a></label>
              <select class="form-control" name="accounts" multiple></select>
              <small class="form-text text-muted">Limit ` + SUBSCRIPTION_N_LIMIT + ` accounts</small>
            </div>
            <div class="form-group">
              <label class="control-label">Coders <a href="` + CODERS_URL + `" target="_blank">` + EXTRA_URL_ICON + `</a></label>
              <select class="form-control" name="coders" multiple></select>
              <small class="form-text text-muted">Limit ` + SUBSCRIPTION_N_LIMIT + ` coders</small>
            </div>
            <div class="form-group">
              <label class="control-label">List <a href="` + LISTS_URL + `" target="_blank">` + EXTRA_URL_ICON + `</a></label>
              <select class="form-control" name="list"></select>
              <small class="form-text text-muted">Use coders and accounts from updated list</small>
            </div>
            <div class="form-group">
              <label class="control-label">Chat <a href="` + CHATS_URL + `" target="_blank">` + EXTRA_URL_ICON + `</a></label>
              <select class="form-control" name="chat"></select>
              <small class="form-text text-muted">Use coders and accounts from updated chat</small>
            </div>
            <div class="form-group">
              <label class="control-label">Method</label>
              <select class="form-control" name="method" required></select>
              <small class="form-text text-muted">Notification method</small>
            </div>
            <input type="hidden" name="no_stage" value="true">
          </form>
        `);

        var $select_resource = form.find('select[name=resource]')
        var $select_no_stage = form.find('input[name=no_stage]')
        var $select_contest = form.find('select[name=contest]')
        var $with_first_accepted = form.find('input[name=with_first_accepted]')
        var $top_n = form.find('input[name=top_n]')
        var $select_accounts = form.find('select[name=accounts]')
        var $select_coders = form.find('select[name=coders]')
        var $select_coder_list = form.find('select[name=list]')
        var $select_coder_chat = form.find('select[name=chat]')
        var $select_method = form.find('select[name=method]')

        bootbox.confirm(form, function(result) {
            if (!result) {
                return
            }

            $('.bootbox-accept').attr('disabled', 'disabled')
            $.ajax({
                type: 'POST',
                url: $.fn.editable.defaults.url,
                data: {
                    pk: $.fn.editable.defaults.pk,
                    name: name,
                    resource: $select_resource.val(),
                    contest: $select_contest.val(),
                    accounts: $select_accounts.val(),
                    coders: $select_coders.val(),
                    coder_list: $select_coder_list.val(),
                    coder_chat: $select_coder_chat.val(),
                    method: $select_method.val(),
                    with_first_accepted: $with_first_accepted.prop('checked'),
                    top_n: $top_n.val(),

                    ...(data && data.id ? {id: data.id} : {}),
                },
                success: (data) => window.location.replace(SUBSCRIPTIONS_URL),
                error: (response) => {
                    $('.bootbox-accept').removeAttr('disabled')
                    log_ajax_error(response)
                },
            })

            return false
        }).on('shown.bs.modal', function() {
            function set_disabled() {
                var disable_addition = !$select_resource.val() && !$select_contest.val()
                $with_first_accepted.prop('disabled', disable_addition)
                $top_n.prop('disabled', disable_addition)

                var disabled_chat_and_list = $select_accounts.val().length || $select_coders.val().length
                var disabled_accounts_and_coders = $select_coder_list.val() || $select_coder_chat.val()
                $select_coders.prop('disabled', disabled_accounts_and_coders)
                $select_accounts.prop('disabled', disabled_accounts_and_coders)
                $select_coder_chat.prop('disabled', $select_coder_list.val() || disabled_chat_and_list)
                $select_coder_list.prop('disabled', $select_coder_chat.val() || disabled_chat_and_list)
            }

            var dropdown_parent = $('.bootbox-confirm .modal-body')
            $select_resource.select2({
                dropdownParent: dropdown_parent,
                dropdownAutoWidth : true,
                width: '100%',
                theme: 'bootstrap',
                placeholder: 'Select resource',
                ajax: select2_ajax_conf('resources', 'text'),
                minimumInputLength: 0,
                allowClear: true,
            })
            $select_resource.on('change', set_disabled)

            $select_contest.select2({
                dropdownParent: dropdown_parent,
                dropdownAutoWidth : true,
                width: '100%',
                theme: 'bootstrap',
                placeholder: 'Select contest',
                ajax: select2_ajax_conf('contests', 'text', {resource: $select_resource, 'no_stage': $select_no_stage}),
                minimumInputLength: 0,
                allowClear: true,
            })
            $select_contest.on('change', set_disabled)

            $with_first_accepted.bootstrapToggle()
            $with_first_accepted.prop('disabled', true)

            $top_n.prop('disabled', true)

            $select_accounts.select2({
                dropdownParent: dropdown_parent,
                dropdownAutoWidth : true,
                width: '100%',
                theme: 'bootstrap',
                placeholder: 'Select accounts',
                ajax: select2_ajax_conf('accounts', 'search', {contest: $select_contest, resource: $select_resource}),
                minimumInputLength: 0,
                allowClear: true,
                multiple: true,
            })
            $select_accounts.on('change', set_disabled)

            $select_coders.select2({
                dropdownParent: dropdown_parent,
                dropdownAutoWidth : true,
                width: '100%',
                theme: 'bootstrap',
                placeholder: 'Select coders',
                ajax: select2_ajax_conf('coders', 'search', {contest: $select_contest, resource: $select_resource}),
                minimumInputLength: 0,
                allowClear: true,
                multiple: true,
            })
            $select_coders.on('change', set_disabled)

            $select_coder_list.select2({
                dropdownParent: dropdown_parent,
                dropdownAutoWidth : true,
                width: '100%',
                theme: 'bootstrap',
                placeholder: 'Select coder list',
                ajax: select2_ajax_conf('coder_lists', 'search'),
                minimumInputLength: 0,
                allowClear: true,
            })
            $select_coder_list.on('change', set_disabled)

            $select_coder_chat.select2({
                dropdownParent: dropdown_parent,
                dropdownAutoWidth : true,
                width: '100%',
                theme: 'bootstrap',
                placeholder: 'Select coder chat',
                ajax: select2_ajax_conf('coder_chats', 'search'),
                minimumInputLength: 0,
                allowClear: true,
            })
            $select_coder_chat.on('change', set_disabled)

            $select_method.select2({
                dropdownParent: dropdown_parent,
                data: SUBSCRIPTIONS_METHODS,
                width: '100%',
                theme: 'bootstrap',
                placeholder: 'Select method',
            })

            if (data) {
                if (data.resource) {
                    $select_resource.select2('trigger', 'select', {data: data.resource})
                }
                if (data.contest) {
                    $select_contest.select2('trigger', 'select', {data: data.contest})
                }
                if (data.coder_list) {
                    $select_coder_list.select2('trigger', 'select', {data: data.coder_list})
                } else if (data.coder_chat) {
                    $select_coder_chat.select2('trigger', 'select', {data: data.coder_chat})
                } else {
                    if (data.accounts) {
                        data.accounts.forEach(option => {
                            $select_accounts.append(new Option(option.text, option.id, true, true)).trigger('change')
                        })
                        $select_accounts.trigger('change')
                    }
                    if (data.coders) {
                        data.coders.forEach(option => {
                            $select_coders.append(new Option(option.text, option.id, true, true)).trigger('change')
                        })
                        $select_coders.trigger('change')
                    }
                }
                if (data.with_first_accepted) {
                    $with_first_accepted.bootstrapToggle('on')
                }
                if (data.top_n) {
                    $top_n.val(data.top_n)
                }
                if (data.method) {
                    $select_method.select2('trigger', 'select', {data: data.method})
                }
            }

            $('.bootbox-confirm').scrollTop(0)
        })
    }

    $('#add-subscription').click(process_subscription)
    $('.edit-subscription').click(process_subscription)

    var ntf_form = $('#notification-form')
    var ntf_add = $('#add-notification')
    $('.edit-notification').click(function() {
        var ntf = $(this).closest('.notification')
        ntf_form.find('[name="pk"]').val($(this).attr('data-id'))
        ntf_form.find('[name="method"]').val(ntf.find('[data-value="method"]').attr('data-val'))
        ntf_form.find('[name="period"]').val(ntf.find('[data-value="period"]').text())
        ntf_form.find('[name="before"]').val(ntf.find('[data-value="before"]').text())
        ntf_form.find('[name="with_updates"]').prop('checked', ntf.find('[data-value="updates"]').length)
        ntf_form.find('[name="with_results"]').prop('checked', ntf.find('[data-value="results"]').length)
        ntf_form.find('[name="with_virtual"]').prop('checked', ntf.find('[data-value="virtual"]').length)
        ntf_form.find('[name="clear_on_delete"]').prop('checked', ntf.find('[data-value="clear"]').length)
        ntf_form.find('[name="add"]').val('Update')
        ntf_add.remove()
        ntf_form.show(300)
    })

    function add_more_filter(div, btn, data) {
        data.items.forEach((el, idx) => {
            var a = $('<a class="badge progress-bar-info shown-filter-contest">').attr('href', el.url).text(el.text)
            a.appendTo(div)
            $('<img width="16" height="16">').attr('src', '/media/sizes/32x32/' + el.icon).prependTo(a)
        })
        if (data.more) {
            var a = $('<a class="action-filter btn btn-default btn-xs">')
            copy_attributes(btn, a)
            a.attr('data-page', parseInt(a.attr('data-page')) + 1)
            a.attr('data-success', 'more_show_filter($this, data)')
            a.click(sentAction)
            a.append($('<i class="fa-fw fas fa-ellipsis-h"></i>'))
            a.appendTo(div)
        }
    }

    function more_show_filter(btn, data) {
        var contests_div = btn.closest('div')
        add_more_filter(contests_div, btn, data)
        $(btn).remove()
    }

    function toggle_show_filter(btn, data) {
        var div = btn.closest('div')
        var previous_shown_filter = div.find('.shown-filter')
        if (previous_shown_filter.length) {
            previous_shown_filter.remove()
            btn.removeClass('active')
        } else if (data) {
            var contests_div = $('<div class="shown-filter">')
            contests_div.appendTo(div)
            add_more_filter(contests_div, btn, data)
            btn.addClass('active')
        }
    }

    function sentAction() {
        var $this = $(this)
        var element_closest = $this.attr('data-closest-element')
        var $element = element_closest? $this.closest(element_closest) : $this.parent()
        var url = $this.attr('data-url') || $.fn.editable.defaults.url
        var name = $this.attr('data-name') || 'name'
        var type = $this.attr('data-type') || 'POST'
        var dialog = undefined

        var data = {
            pk: $.fn.editable.defaults.pk,
            [name]: $this.attr('data-action'),
            id: $this.data("id"),
        }

        var page = $this.attr('data-page')
        if (page) {
            data['page'] = page
        }

        function queryAction() {
            if (dialog) dialog.find('.bootbox-accept').attr('disabled', 'disabled')
            $.ajax({
                type: type,
                url: url,
                data: data,
                success: function(data) {
                    eval($this.attr('data-success'))
                    if (dialog) dialog.modal('hide')
                },
                error: (response) => log_ajax_error(response),
                complete: () => {
                    if (dialog) dialog.find('.bootbox-accept').removeAttr('disabled')
                }
            })
        }

        if ($this.attr('data-confirm') === 'false') {
            queryAction()
        } else {
            dialog = bootbox.confirm({
                size: 'small',
                message: $element.text() +
                    "<br/><br/>" +
                    "<b>" + $this.attr('data-action').replace('-', ' ').toTitleCase() + "?</b>",
                callback: (result) => {
                    if (!result) {
                        return
                    }
                    queryAction()
                    return false
                },
            })
        }
        return false
    }
    $('.action-notification').click(sentAction)
    $('.action-filter').click(sentAction)
    $('.action-list').click(sentAction)
    $('.action-calendar').click(sentAction)
    $('.action-subscription').click(sentAction)

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

    var $search_resource = $('select#add-account-resource')
    $search_resource.select2({
        width: '40%',
        allowClear: true,
        placeholder: 'Search resource by regex',
        data: SELECTED_RESOURCE,
        ajax: {
            url: '/settings/search/',
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

    function deleteAccount() {
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
                            id: $account.find('.delete-account').attr('data-id'),
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
    }

    $('.delete-account').click(deleteAccount)

    var $account_suggests = $('#account-suggests')

    function selectAccountSuggest() {
        $search_account.val($(this).data('handle')).trigger('change')
        $account_suggests.children().remove()
    }

    function addAccountSuggest(account) {
        var $suggest = $('<a>', {
            class: 'account-suggest badge progress-bar-info',
            data: {handle: account.account},
            text: account.account + (account.name && account.account.indexOf(account.name) == -1? ' | ' + account.name : '')
        })
        $suggest.click(selectAccountSuggest)
        $account_suggests.append($suggest)
    }

    var $search_account = $('#add-account-search')
    $search_account.css({'width': '40%'});

    var $add_account_button = $('#add-account')
    var $add_account_loading = $('#add-account-loading')

    function update_advanced_search() {
        $add_account_button.prop('disabled', !($search_resource.val() && $search_account.val()))

        $advanced_search = $('#add-account-advanced-search')
        href = ACCOUNTS_ADVANCED_SEARCH_URL
        if ($search_resource.val()) {
            href += '&resource=' + $search_resource.val()
        }
        if ($search_account.val()) {
            href += '&search=' + encodeURIComponent($search_account.val())
        }
        $advanced_search.attr('href', href)
    }

    $search_resource.on('change', update_advanced_search)
    $search_account.on('keyup', update_advanced_search)
    update_advanced_search()

    function filter_account_table() {
        var resource_pk = $search_resource.val()
        if (resource_pk) {
            $('#list-accounts .account').addClass('hidden')
            $('#list-accounts .account[data-account-resource="' + resource_pk + '"]').removeClass('hidden')
        } else {
            $('#list-accounts .account').removeClass('hidden')
        }
    }
    $search_resource.on('change', filter_account_table)
    filter_account_table()

    $add_account_button.click(function() {
        $add_account_loading.removeClass('hidden')
        $add_account_button.prop('disabled', true)
        $.ajax({
            type: 'POST',
            url: $.fn.editable.defaults.url,
            data: {
                pk: $.fn.editable.defaults.pk,
                name: 'add-account',
                resource: $search_resource.val(),
                value: $search_account.val(),
            },
            success: function(data) {
                if (data.message == 'add') {
                    window.location.replace(ACCOUNTS_TAB_URL + '?resource=' + encodeURIComponent($search_resource.val()))
                    return
                }

                $add_account_loading.addClass('hidden')
                $add_account_button.prop('disabled', false)
                if (data.message == 'suggest') {
                    $account_suggests.children().remove()
                    for (var i = 0; i < data.accounts.length; i++) {
                        addAccountSuggest(data.accounts[i])
                    }
                }
            },
            error: function(data) {
                if (data.responseJSON && data.responseJSON.message == 'redirect') {
                    window.location.replace(data.responseJSON.url)
                    return
                }
                $add_account_loading.addClass('hidden')
                $add_account_button.prop('disabled', false)
                $errorAccountTab.show().html(data.responseText)
                setTimeout(function() { $errorAccountTab.hide(500) }, 3000)
            },
        })
    })

    $search_account.keypress(function(e) {
        if (e.which == 13 ) {
            e.preventDefault()
            $add_account_button.click()
        }
    })

    var $search_org = $('#organization-search')
    $search_org.select2({
        width: '50%',
        ajax: {
            url: '/settings/search/',
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

    var $delete_user = $('#delete-user')
    $delete_user.click(function() {
        $.ajax({
            type: 'POST',
            url: $.fn.editable.defaults.url,
            data: {
                pk: $.fn.editable.defaults.pk,
                name: 'pre-delete-user',
            },
            success: function(data) {
                bootbox.prompt({
                    size: 'medium',
                    title: 'Delete user?',
                    message: 'Data to be deleted:<pre>' + data.data + '</pre>Enter your username to be deleted:',
                    callback: function(result) {
                        if (result) {
                            $.ajax({
                                type: 'POST',
                                url: $.fn.editable.defaults.url,
                                data: {
                                    pk: $.fn.editable.defaults.pk,
                                    username: result,
                                    name: 'delete-user',
                                },
                                success: function(data) {
                                    document.location.href = "/"
                                },
                                error: function(data) {
                                    notify(data.responseText, "error")
                                },
                            })
                        }
                    },
                    onShown: function(e) {
                        var btn = $('.btn.btn-danger.bootbox-accept')
                        btn.addClass('disabled')
                        $('.bootbox-input-text').keyup(function() {
                            if ($(this).val() == USERNAME) {
                                btn.removeClass('disabled')
                            } else {
                                btn.addClass('disabled')
                            }
                        })
                    },
                    buttons: {
                        confirm: {
                            label: 'Delete user',
                            className: 'btn-danger',
                        },
                    },
                })
            },
            error: function(data) {
                notify(data.responseText, "error")
            },
        })
    })
})
