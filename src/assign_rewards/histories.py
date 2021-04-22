

def process_incoming_history_file_group(file_group):

    stats = utils.create_stats()

    # get the hashed history id
    hashed_history_id = hashed_history_id_from_file(file_group[0])
    
    # add any previously saved history files for this hashed history id
    file_group.extend(history_files_for_hashed_history_id(hashed_history_id, stats))

    # load all records
    records = load_history(file_group, stats)

    # write the consolidated records to a new history file
    save_history(hashed_history_id, records)
    
    # perform validation after consolidation so that invalid records are retained
    # this ensures that any bugs in user-supplied validation code doesn't cause records to be lost
    records = filter_valid_records(hashed_history_id, records)

    # assign rewards to decision records.
    rewarded_decisions_by_model = assign_rewards_to_decisions(records)
    
    # upload the updated rewarded decision records to S3
    for model, rewarded_decisions in rewarded_decisions_by_model.items():
        upload_rewarded_decisions(model, hashed_history_id, rewarded_decisions)
    
    # delete the incoming and history files that were processed
    delete_all(file_group)
    
    return stats

def load_history(file_group, stats):
    records = []
    message_ids = set()
    
    for file in file_group:
        records.extend(load_records(file, message_ids, stats))
            
    return records


def load_records(file, message_ids, stats):
    """
    Load a gzipped jsonlines file
    
    Args:
        filename: name of the input gzipped jsonlines file to load
    
    Returns:
        A list of records
    """

    records = []
    error = None

    try:
        with gzip.open(file.absolute(), mode="rt", encoding="utf8") as gzf:
            for line in gzf.readlines():
                # Do a inner try/except to try to recover as many records as possible
                try: 
                    record = json.loads(line)
                    # parse the timestamp into a datetime since it will be used often
                    record[TIMESTAMP_KEY] = dateutil.parser.parse(record[TIMESTAMP_KEY])
                    
                    message_id = record[MESSAGE_ID_KEY]
                    if not message_id in message_ids:
                        message_ids.add(message_id)
                        records.append(record)
                    else:
                        stats[DUPLICATE_MESSAGE_ID_COUNT] += 1
                except (json.decoder.JSONDecodeError, ValueError) as e:
                    error = e
    except (zlib.error, EOFError, gzip.BadGzipFile) as e:
        # gzip can throw zlib.error, EOFError, or gzip.BadGZipFile on corrupt file
        error = e
        
    if error:
        # Unrecoverable parse error, copy file to /unrecoverable
        print(f'unrecoverable parse error "{error}", copying {file.absolute()} to {config.UNRECOVERABLE_PATH.absolute()}')
        stats[UNRECOVERABLE_PARSE_ERROR_COUNT] += 1
        copy_to_unrecoverable(file)
    
    
    stats[RECORD_COUNT] += len(records)

    return records


def select_incoming_history_files():
    # hash based on the first 8 characters of the hashed history id
    return select_files_for_node(INCOMING_HISTORIES_PATH, '*.jsonl.gz')
    # TODO check valid file name & hashed history id chars
    
def save_history(hashed_history_id, history_records):
    
    output_file = history_dir_for_hashed_history_id(hashed_history_id) / f'{hashed_history_id}-{uuid.uuid4()}.jsonl.gz'
    save_gzipped_jsonlines(output_file.absolute(), history_records)

def unique_hashed_history_file_name(hashed_history_id):
    return f'{hashed_history_id}-{uuid.uuid4()}.jsonl.gz'
    
def hashed_history_id_from_file(file):
    return file.name.split('-')[0]

def history_dir_for_hashed_history_id(hashed_history_id):
    # returns a path like /mnt/histories/1c/aa
    return config.HISTORIES_PATH / sub_dir_for_hashed_history_id(hashed_history_id)

def incoming_history_dir_for_hashed_history_id(hashed_history_id):
    # returns a path like /mnt/incoming_histories/1c/aa
    return config.INCOMING_HISTORIES_PATH / sub_dir_for_hashed_history_id(hashed_history_id)

def sub_dir_for_hashed_history_id(hashed_history_id):
    # returns a path like /mnt/histories/1c/aa
    return hashed_history_id[0:2] / hashed_history_id[2:4]

def history_files_for_hashed_history_id(hashed_history_id, stats):
    results = list(history_dir_for_hashed_history_id(hashed_history_id).glob(f'{hashed_history_id}-*.jsonl.gz'))
    stats[PROCESSED_HISTORY_FILE_COUNT] += len(results)
    return results

def group_files_by_hashed_history_id(files):
    sorted_files = sorted(files, key=hashed_history_id_from_file)
    return [list(it) for k, it in groupby(sorted_files, hashed_history_id_from_file)]    