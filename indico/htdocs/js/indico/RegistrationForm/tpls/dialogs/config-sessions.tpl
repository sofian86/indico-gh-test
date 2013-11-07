<form>
    <div class="regFormDialogEditLine">
        <label class="regFormDialogCaption" style="width : 180px">
            {{ _ "Type of sessions' form" | i18n }}
        </label>
        <select name="type">
            <option value="2priorities" {{ "selected" if type == "2priorities" }}>
                {{ '2 choices' | i18n }}
            </option>
            <option value="all" {{ "selected" if type == "all" }}>
                {{ 'multiple' | i18n }}
            </option>
        </select>
    </div>
    <span> {{ 'How many sessions the registrant can choose.' | i18n }}
        <br> {{ 'Please note that billing is not possible when using 2 choices' | i18n }}
    </span>
</form>