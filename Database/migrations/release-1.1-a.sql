/**
 * Event to remove data from COLLECTED_DATA table after 7 days.
 */
CREATE EVENT remove_collected_data ON SCHEDULE EVERY 1 DAY DO DELETE FROM COLLECTED_DATA WHERE pull_date < NOW() - INTERVAL 7 DAY;
SET GLOBAL event_scheduler = 1;