@upload_bp.route('/upload-commodity', methods=['GET', 'POST'])
def upload_commodity():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename.endswith('.csv'):
            flash('Please upload a valid CSV file.', 'danger')
            return redirect(request.url)

        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        reader = csv.DictReader(stream)

        for row in reader:
            fund_name = row['Fund Name'].strip()
            sub_category_name = row['Sub Category'].strip()
            units = Decimal(row['Units'])
            nav = Decimal(row['NAV'])
            amount = Decimal(row['Amount Invested'])
            broker_name = row['Broker Name'].strip()
            buy_date = datetime.strptime(row['Buy Date'], "%Y-%m-%d").date()

            # Lookup or create subcategory and category
            subcat = SubCategory.query.filter_by(name=sub_category_name).first()
            if not subcat:
                commodity_cat = Category.query.filter_by(name='Commodity').first()
                subcat = SubCategory(name=sub_category_name, category=commodity_cat)
                db.session.add(subcat)
                db.session.flush()

            # Lookup or create fund
            fund = Fund.query.filter_by(name=fund_name).first()
            if not fund:
                fund = Fund(name=fund_name, sub_category=subcat, latest_nav=nav, broker_name=broker_name)
                db.session.add(fund)
                db.session.flush()

            # Create investment
            inv = Investment(
                user_id=current_user.id,
                fund_id=fund.id,
                transaction_type='Buy',
                units=units,
                amount=amount,
                date=buy_date
            )
            db.session.add(inv)

        db.session.commit()
        flash('Commodity data uploaded successfully.', 'success')
        return redirect(url_for('dashboard_tables_bp.dashboard_tables', user_id=current_user.id))

    return render_template('upload_commodity.html')
